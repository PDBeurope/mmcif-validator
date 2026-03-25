/**
 * Extension configuration and resolved paths (dictionary, script).
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

const COMMON_DICT_NAMES = ['mmcif_pdbx_v5_next.dic', 'mmcif_pdbx_5408.dic', 'mmcif_pdbx.dic'];

/**
 * When `mmcifValidator.pythonPath` is empty, pick a sensible default.
 * Ubuntu 24.04+ and other Linux installs often have `python3` but no `python` on PATH.
 * Windows Python installs typically expose `python` (not always `python3`).
 */
function defaultPythonExecutable(): string {
    return process.platform === 'win32' ? 'python' : 'python3';
}

export interface ValidatorSettings {
    enabled: boolean;
    dictionaryPath: string;
    dictionaryUrl: string;
    pythonPath: string;
    validationTimeoutMs: number;
}

export function getSettings(): ValidatorSettings {
    const config = vscode.workspace.getConfiguration('mmcifValidator');
    const validationTimeoutSeconds = config.get<number>('validationTimeoutSeconds', 60);
    const pythonPathRaw = config.get<string>('pythonPath', '');
    const pythonPath =
        pythonPathRaw !== undefined && pythonPathRaw.trim() !== ''
            ? pythonPathRaw.trim()
            : defaultPythonExecutable();
    return {
        enabled: config.get<boolean>('enabled', true),
        dictionaryPath: config.get<string>('dictionaryPath', ''),
        dictionaryUrl: config.get<string>('dictionaryUrl', 'http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic'),
        pythonPath,
        validationTimeoutMs: Math.max(5000, Math.min(600000, validationTimeoutSeconds * 1000)),
    };
}

export interface DictionarySource {
    dictSource: string;
    useUrl: boolean;
}

export function getDictionarySource(workspaceFolder: vscode.WorkspaceFolder | undefined, getCachedPath: () => string | null): DictionarySource | null {
    const config = vscode.workspace.getConfiguration('mmcifValidator');
    const dictionaryUrl = config.get<string>('dictionaryUrl', 'http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic');
    const dictionaryPath = config.get<string>('dictionaryPath', '');

    let dictSource: string | null = null;
    let useUrl = false;

    if (dictionaryUrl) {
        dictSource = dictionaryUrl;
        useUrl = true;
    } else if (dictionaryPath) {
        dictSource = path.isAbsolute(dictionaryPath)
            ? dictionaryPath
            : workspaceFolder
                ? path.join(workspaceFolder.uri.fsPath, dictionaryPath)
                : dictionaryPath;
    } else if (workspaceFolder) {
        for (const name of COMMON_DICT_NAMES) {
            const p = path.join(workspaceFolder.uri.fsPath, name);
            if (fs.existsSync(p)) {
                dictSource = p;
                break;
            }
        }
    }

    if (!dictSource && workspaceFolder) {
        for (const name of COMMON_DICT_NAMES) {
            const p = path.join(workspaceFolder.uri.fsPath, name);
            if (fs.existsSync(p)) {
                dictSource = p;
                break;
            }
        }
    }
    if (!dictSource) {
        const cached = getCachedPath();
        if (cached && fs.existsSync(cached)) {
            dictSource = cached;
        } else {
            dictSource = 'http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic';
            useUrl = true;
        }
    }

    return dictSource ? { dictSource, useUrl } : null;
}

export function getScriptPath(extensionPath: string | undefined): string | null {
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
    const possiblePaths = [
        path.join(__dirname, '..', 'python-script', 'validate_mmcif.py'),
        path.join(extensionPath || '', 'python-script', 'validate_mmcif.py'),
        path.join(workspacePath, 'python-script', 'validate_mmcif.py'),
        path.join(workspacePath, 'validate_mmcif.py'),
    ];
    if (extensionPath) {
        possiblePaths.push(
            path.join(extensionPath, 'python-script', 'validate_mmcif.py'),
            path.join(extensionPath, 'validate_mmcif.py')
        );
    }
    return possiblePaths.find(p => fs.existsSync(p)) ?? null;
}
