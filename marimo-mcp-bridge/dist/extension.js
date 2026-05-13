"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const http = __importStar(require("http"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const BRIDGE_PORT = 42018;
let server;
function activate(context) {
    server = http.createServer(handleRequest);
    server.listen(BRIDGE_PORT, '127.0.0.1', () => {
        console.log(`marimo-mcp-bridge listening on port ${BRIDGE_PORT}`);
    });
    server.on('error', (err) => {
        if (err.code === 'EADDRINUSE') {
            vscode.window.showWarningMessage(`marimo-mcp-bridge: port ${BRIDGE_PORT} already in use — bridge not started`);
        }
    });
    context.subscriptions.push({ dispose: () => server?.close() });
}
function deactivate() {
    server?.close();
}
function handleRequest(req, res) {
    res.setHeader('Content-Type', 'application/json');
    if (req.method === 'GET' && req.url === '/health') {
        send(res, 200, { status: 'ok' });
        return;
    }
    if (req.method === 'GET' && req.url === '/notebooks') {
        try {
            send(res, 200, getOpenNotebooks());
        }
        catch (e) {
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
                const { method, params } = JSON.parse(body);
                const result = await callMarimoApi(method, params);
                send(res, 200, { result: result ?? null });
            }
            catch (e) {
                send(res, 500, { error: String(e) });
            }
        });
        return;
    }
    send(res, 404, { error: 'Not found' });
}
async function debugInfo() {
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
function send(res, status, data) {
    res.writeHead(status);
    res.end(JSON.stringify(data));
}
function readBody(req, cb) {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => cb(Buffer.concat(chunks).toString('utf8')));
}
function getOpenNotebooks() {
    return vscode.workspace.notebookDocuments
        .filter((doc) => doc.notebookType === 'marimo-notebook')
        .map((doc) => {
        const cells = [];
        for (let i = 0; i < doc.cellCount; i++) {
            const cell = doc.cellAt(i);
            const stableId = cell.metadata?.stableId;
            if (typeof stableId === 'string' && stableId) {
                cells.push({ cellId: stableId, code: cell.document.getText() });
            }
        }
        return { uri: doc.uri.toString(), path: doc.uri.fsPath, cells };
    });
}
function findCellCode(notebookUri, cellId) {
    const doc = vscode.workspace.notebookDocuments.find(d => d.uri.toString() === notebookUri);
    if (!doc)
        return undefined;
    for (let i = 0; i < doc.cellCount; i++) {
        const cell = doc.cellAt(i);
        const stableId = cell.metadata?.stableId;
        if (stableId === cellId)
            return cell.document.getText();
    }
    return undefined;
}
function getCellOutputs(notebookUri, cellId) {
    const doc = vscode.workspace.notebookDocuments.find(d => d.uri.toString() === notebookUri);
    if (!doc)
        return { error: 'Notebook not found' };
    for (let i = 0; i < doc.cellCount; i++) {
        const cell = doc.cellAt(i);
        const stableId = cell.metadata?.stableId;
        if (stableId !== cellId)
            continue;
        const outputs = cell.outputs.map(output => ({
            items: output.items.map(item => {
                const isText = item.mime.startsWith('text/')
                    || item.mime === 'application/json'
                    || item.mime === 'application/vnd.code.notebook.stdout'
                    || item.mime === 'application/vnd.code.notebook.stderr';
                if (isText) {
                    return { mime: item.mime, text: Buffer.from(item.data).toString('utf-8') };
                }
                else {
                    return { mime: item.mime, base64: Buffer.from(item.data).toString('base64') };
                }
            }),
        }));
        return { cellId, outputs };
    }
    return { error: `Cell ${cellId} not found` };
}
async function getPythonExecutable(notebookUri) {
    // 1. .venv next to the notebook file
    if (notebookUri) {
        const notebookPath = vscode.Uri.parse(notebookUri).fsPath;
        const venvPython = path.join(path.dirname(notebookPath), '.venv', 'bin', 'python');
        if (fs.existsSync(venvPython))
            return venvPython;
    }
    // 2. .venv in any workspace folder
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
        const venvPython = path.join(folder.uri.fsPath, '.venv', 'bin', 'python');
        if (fs.existsSync(venvPython))
            return venvPython;
    }
    // 3. VS Code Python extension — respects user's interpreter selection
    try {
        const ext = vscode.extensions.getExtension('ms-python.python');
        if (ext) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const api = (await ext.activate());
            const resource = notebookUri
                ? vscode.Uri.parse(notebookUri)
                : vscode.workspace.workspaceFolders?.[0]?.uri;
            const envPath = await api?.environments?.getActiveEnvironmentPath?.(resource);
            if (envPath?.path)
                return envPath.path;
            const details = api?.settings?.getExecutionDetails?.(resource);
            if (details?.execCommand?.[0])
                return details.execCommand[0];
        }
    }
    catch {
        // fall through
    }
    return 'python3';
}
async function callMarimoApi(method, params) {
    let commandParams;
    if (method === 'execute-cells') {
        const { notebookUri, cellIds, codes } = params;
        const executable = await getPythonExecutable(notebookUri);
        commandParams = { notebookUri, executable, inner: { cellIds, codes } };
    }
    else if (method === 'run-cell') {
        const { notebookUri, cellId } = params;
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
    }
    else if (method === 'get-cell-output') {
        const { notebookUri, cellId } = params;
        return getCellOutputs(notebookUri, cellId);
    }
    else if (method === 'delete-cell') {
        const { notebookUri, cellId } = params;
        const doc = vscode.workspace.notebookDocuments.find(d => d.uri.toString() === notebookUri);
        if (!doc)
            throw new Error(`Notebook not found: ${notebookUri}`);
        for (let i = 0; i < doc.cellCount; i++) {
            const cell = doc.cellAt(i);
            const stableId = cell.metadata?.stableId;
            if (stableId === cellId) {
                const edit = new vscode.WorkspaceEdit();
                edit.set(doc.uri, [vscode.NotebookEdit.deleteCells(new vscode.NotebookRange(i, i + 1))]);
                const success = await vscode.workspace.applyEdit(edit);
                return success ? { deleted: cellId } : null;
            }
        }
        throw new Error(`Cell ${cellId} not found in ${notebookUri}`);
    }
    else if (method === 'add-cell') {
        const { notebookUri, cellId, code, afterCellId } = params;
        const doc = vscode.workspace.notebookDocuments.find(d => d.uri.toString() === notebookUri);
        if (!doc)
            throw new Error(`Notebook not found: ${notebookUri}`);
        let insertIndex = doc.cellCount;
        if (afterCellId !== null) {
            for (let i = 0; i < doc.cellCount; i++) {
                const cell = doc.cellAt(i);
                const stableId = cell.metadata?.stableId;
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
    }
    else if (method === 'execute-and-poll-outputs') {
        const { notebookUri, cellId, code } = params;
        const executable = await getPythonExecutable(notebookUri);
        // Snapshot outputs before execution to detect changes
        const before = JSON.stringify(getCellOutputs(notebookUri, cellId));
        await vscode.commands.executeCommand('marimo.api', {
            method: 'execute-cells',
            params: { notebookUri, executable, inner: { cellIds: [cellId], codes: [code] } },
        });
        // Poll until outputs change from pre-execution state (handles both empty→filled and stale→updated)
        const deadline = Date.now() + 15000;
        while (Date.now() < deadline) {
            await new Promise(r => setTimeout(r, 300));
            const current = JSON.stringify(getCellOutputs(notebookUri, cellId));
            if (current !== before) {
                return getCellOutputs(notebookUri, cellId);
            }
        }
        return getCellOutputs(notebookUri, cellId);
    }
    else {
        commandParams = params;
    }
    return vscode.commands.executeCommand('marimo.api', {
        method,
        params: commandParams,
    });
}
