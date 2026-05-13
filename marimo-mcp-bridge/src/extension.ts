import * as vscode from 'vscode';
import * as http from 'http';
import * as fs from 'fs';
import * as path from 'path';

const BRIDGE_PORT = 42018;

let server: http.Server | undefined;

export function activate(context: vscode.ExtensionContext): void {
    server = http.createServer(handleRequest);
    server.listen(BRIDGE_PORT, '127.0.0.1', () => {
        console.log(`marimo-mcp-bridge listening on port ${BRIDGE_PORT}`);
    });
    server.on('error', (err: NodeJS.ErrnoException) => {
        if (err.code === 'EADDRINUSE') {
            vscode.window.showWarningMessage(
                `marimo-mcp-bridge: port ${BRIDGE_PORT} already in use — bridge not started`
            );
        }
    });
    context.subscriptions.push({ dispose: () => server?.close() });
}

export function deactivate(): void {
    server?.close();
}

function handleRequest(req: http.IncomingMessage, res: http.ServerResponse): void {
    res.setHeader('Content-Type', 'application/json');

    if (req.method === 'GET' && req.url === '/health') {
        send(res, 200, { status: 'ok' });
        return;
    }

    if (req.method === 'GET' && req.url === '/notebooks') {
        try {
            send(res, 200, getOpenNotebooks());
        } catch (e) {
            send(res, 500, { error: String(e) });
        }
        return;
    }

    if (req.method === 'GET' && req.url === '/debug') {
        debugInfo().then(info => send(res, 200, info)).catch(e => send(res, 500, { error: String(e) }));
        return;
    }

    if (req.method === 'POST' && req.url === '/api') {
        readBody(req, async (body) => {
            try {
                const { method, params } = JSON.parse(body) as {
                    method: string;
                    params: Record<string, unknown>;
                };
                const result = await callMarimoApi(method, params);
                send(res, 200, { result: result ?? null });
            } catch (e) {
                send(res, 500, { error: String(e) });
            }
        });
        return;
    }

    send(res, 404, { error: 'Not found' });
}

async function debugInfo(): Promise<object> {
    const executable = await getPythonExecutable();
    return {
        executable,
        workspaceFolders: vscode.workspace.workspaceFolders?.map(f => f.uri.fsPath) ?? [],
        openNotebooks: vscode.workspace.notebookDocuments.map(d => ({
            type: d.notebookType,
            uri: d.uri.toString(),
        })),
    };
}

function send(res: http.ServerResponse, status: number, data: unknown): void {
    res.writeHead(status);
    res.end(JSON.stringify(data));
}

function readBody(req: http.IncomingMessage, cb: (body: string) => void): void {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => cb(Buffer.concat(chunks).toString('utf8')));
}

interface CellInfo {
    cellId: string;
    code: string;
}

interface NotebookInfo {
    uri: string;
    path: string;
    cells: CellInfo[];
}

function getOpenNotebooks(): NotebookInfo[] {
    return vscode.workspace.notebookDocuments
        .filter((doc) => doc.notebookType === 'marimo-notebook')
        .map((doc) => {
            const cells: CellInfo[] = [];
            for (let i = 0; i < doc.cellCount; i++) {
                const cell = doc.cellAt(i);
                const stableId = (cell.metadata as Record<string, unknown>)?.stableId;
                if (typeof stableId === 'string' && stableId) {
                    cells.push({ cellId: stableId, code: cell.document.getText() });
                }
            }
            return { uri: doc.uri.toString(), path: doc.uri.fsPath, cells };
        });
}

function findCellCode(notebookUri: string, cellId: string): string | undefined {
    const doc = vscode.workspace.notebookDocuments.find(
        d => d.uri.toString() === notebookUri
    );
    if (!doc) return undefined;
    for (let i = 0; i < doc.cellCount; i++) {
        const cell = doc.cellAt(i);
        const stableId = (cell.metadata as Record<string, unknown>)?.stableId;
        if (stableId === cellId) return cell.document.getText();
    }
    return undefined;
}

function getCellOutputs(notebookUri: string, cellId: string): object {
    const doc = vscode.workspace.notebookDocuments.find(
        d => d.uri.toString() === notebookUri
    );
    if (!doc) return { error: 'Notebook not found' };

    for (let i = 0; i < doc.cellCount; i++) {
        const cell = doc.cellAt(i);
        const stableId = (cell.metadata as Record<string, unknown>)?.stableId;
        if (stableId !== cellId) continue;

        const outputs = cell.outputs.map(output => ({
            items: output.items.map(item => {
                const isText = item.mime.startsWith('text/')
                    || item.mime === 'application/json'
                    || item.mime === 'application/vnd.code.notebook.stdout'
                    || item.mime === 'application/vnd.code.notebook.stderr';
                if (isText) {
                    return { mime: item.mime, text: Buffer.from(item.data).toString('utf-8') };
                } else {
                    return { mime: item.mime, base64: Buffer.from(item.data).toString('base64') };
                }
            }),
        }));
        return { cellId, outputs };
    }
    return { error: `Cell ${cellId} not found` };
}

async function getPythonExecutable(notebookUri?: string): Promise<string> {
    // 1. .venv next to the notebook file
    if (notebookUri) {
        const notebookPath = vscode.Uri.parse(notebookUri).fsPath;
        const venvPython = path.join(path.dirname(notebookPath), '.venv', 'bin', 'python');
        if (fs.existsSync(venvPython)) return venvPython;
    }

    // 2. .venv in any workspace folder
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
        const venvPython = path.join(folder.uri.fsPath, '.venv', 'bin', 'python');
        if (fs.existsSync(venvPython)) return venvPython;
    }

    // 3. VS Code Python extension — respects user's interpreter selection
    try {
        const ext = vscode.extensions.getExtension('ms-python.python');
        if (ext) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const api = (await ext.activate()) as any;
            const resource = notebookUri
                ? vscode.Uri.parse(notebookUri)
                : vscode.workspace.workspaceFolders?.[0]?.uri;
            const envPath = await api?.environments?.getActiveEnvironmentPath?.(resource);
            if (envPath?.path) return envPath.path as string;
            const details = api?.settings?.getExecutionDetails?.(resource);
            if (details?.execCommand?.[0]) return details.execCommand[0] as string;
        }
    } catch {
        // fall through
    }

    return 'python3';
}

async function callMarimoApi(
    method: string,
    params: Record<string, unknown>
): Promise<unknown> {
    let commandParams: Record<string, unknown>;

    if (method === 'execute-cells') {
        const { notebookUri, cellIds, codes } = params as {
            notebookUri: string;
            cellIds: string[];
            codes: string[];
        };
        const executable = await getPythonExecutable(notebookUri);
        commandParams = { notebookUri, executable, inner: { cellIds, codes } };

    } else if (method === 'run-cell') {
        const { notebookUri, cellId } = params as {
            notebookUri: string;
            cellId: string;
        };
        const code = findCellCode(notebookUri, cellId);
        if (code === undefined) {
            throw new Error(`Cell ${cellId} not found in ${notebookUri}`);
        }
        const executable = await getPythonExecutable(notebookUri);
        commandParams = { notebookUri, executable, inner: { cellIds: [cellId], codes: [code] } };
        return vscode.commands.executeCommand('marimo.api', {
            method: 'execute-cells',
            params: commandParams,
        });

    } else if (method === 'get-cell-output') {
        const { notebookUri, cellId } = params as {
            notebookUri: string;
            cellId: string;
        };
        return getCellOutputs(notebookUri, cellId);

    } else if (method === 'delete-cell') {
        const { notebookUri, cellId } = params as {
            notebookUri: string;
            cellId: string;
        };
        const doc = vscode.workspace.notebookDocuments.find(
            d => d.uri.toString() === notebookUri
        );
        if (!doc) throw new Error(`Notebook not found: ${notebookUri}`);
        for (let i = 0; i < doc.cellCount; i++) {
            const cell = doc.cellAt(i);
            const stableId = (cell.metadata as Record<string, unknown>)?.stableId;
            if (stableId === cellId) {
                const edit = new vscode.WorkspaceEdit();
                edit.set(doc.uri, [vscode.NotebookEdit.deleteCells(new vscode.NotebookRange(i, i + 1))]);
                const success = await vscode.workspace.applyEdit(edit);
                return success ? { deleted: cellId } : null;
            }
        }
        throw new Error(`Cell ${cellId} not found in ${notebookUri}`);

    } else if (method === 'add-cell') {
        const { notebookUri, cellId, code, afterCellId } = params as {
            notebookUri: string;
            cellId: string;
            code: string;
            afterCellId: string | null;
        };
        const doc = vscode.workspace.notebookDocuments.find(
            d => d.uri.toString() === notebookUri
        );
        if (!doc) throw new Error(`Notebook not found: ${notebookUri}`);

        let insertIndex = doc.cellCount;
        if (afterCellId !== null) {
            for (let i = 0; i < doc.cellCount; i++) {
                const cell = doc.cellAt(i);
                const stableId = (cell.metadata as Record<string, unknown>)?.stableId;
                if (stableId === afterCellId) {
                    insertIndex = i + 1;
                    break;
                }
            }
        }

        const newCell = new vscode.NotebookCellData(vscode.NotebookCellKind.Code, code, 'python');
        newCell.metadata = { stableId: cellId };
        const edit = new vscode.WorkspaceEdit();
        edit.set(doc.uri, [vscode.NotebookEdit.insertCells(insertIndex, [newCell])]);
        const success = await vscode.workspace.applyEdit(edit);
        return success ? { cellId } : null;

    } else if (method === 'execute-and-poll-outputs') {
        const { notebookUri, cellId, code } = params as {
            notebookUri: string;
            cellId: string;
            code: string;
        };
        const executable = await getPythonExecutable(notebookUri);
        await vscode.commands.executeCommand('marimo.api', {
            method: 'execute-cells',
            params: { notebookUri, executable, inner: { cellIds: [cellId], codes: [code] } },
        });
        const deadline = Date.now() + 15000;
        while (Date.now() < deadline) {
            await new Promise<void>(r => setTimeout(r, 300));
            const result = getCellOutputs(notebookUri, cellId) as { outputs?: unknown[]; error?: string };
            if (result.outputs && result.outputs.length > 0) {
                return result;
            }
        }
        return getCellOutputs(notebookUri, cellId);

    } else {
        commandParams = params;
    }

    return vscode.commands.executeCommand('marimo.api', {
        method,
        params: commandParams,
    });
}
