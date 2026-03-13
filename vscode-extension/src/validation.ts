/**
 * Validation: run Python script, parse protocol output (validation result or script failure), build diagnostics.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { exec } from 'child_process';
import { promisify } from 'util';
import {
    ValidationErrorItem,
    ValidationResult,
    MetadataCompleteness,
    DepositionMissingItem,
    ScriptFailure,
    ErrorCode,
    isScriptFailure,
    isValidationResult,
} from './types';
import { getSettings, getDictionarySource, getScriptPath } from './config';
import { getCachedDictionaryPath, downloadAndCacheDictionary } from './dictionary';

const execAsync = promisify(exec);

export interface ValidationContext {
    outputChannel: vscode.OutputChannel;
    extensionPath: string | undefined;
    depositionStatusBarItem?: vscode.StatusBarItem;
    /**
     * Callback when metadata completeness has been computed for a document.
     * The first argument is the document URI as a string.
     */
    onDepositionUpdate?: (uri: string, dep: MetadataCompleteness | null) => void;
}

/**
 * Find first JSON object in stdout (validation result or script failure).
 */
function extractJsonFromStdout(stdout: string): unknown {
    const lines = stdout.split('\n');
    let jsonStart = -1;
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].trim().startsWith('{')) {
            jsonStart = i;
            break;
        }
    }
    if (jsonStart < 0) return null;

    let braceCount = 0;
    let jsonEnd = jsonStart;
    for (let i = jsonStart; i < lines.length; i++) {
        for (const ch of lines[i]) {
            if (ch === '{') braceCount++;
            if (ch === '}') braceCount--;
        }
        if (braceCount === 0) {
            jsonEnd = i;
            break;
        }
    }
    const jsonStr = lines.slice(jsonStart, jsonEnd + 1).join('\n').trim();
    try {
        return JSON.parse(jsonStr);
    } catch {
        return null;
    }
}

function errorToRange(document: vscode.TextDocument, error: ValidationErrorItem): vscode.Range {
    const line = Math.max(0, error.line - 1);
    try {
        const lineText = document.lineAt(line).text;
        if (error.start_char != null && error.end_char != null) {
            return new vscode.Range(line, error.start_char, line, error.end_char);
        }
        const valueMatch = error.message.match(/Value '([^']+)'/);
        if (valueMatch && valueMatch[1]) {
            const valueToFind = valueMatch[1];
            let valueIndex = lineText.indexOf(`'${valueToFind}'`);
            if (valueIndex < 0) valueIndex = lineText.indexOf(`"${valueToFind}"`);
            if (valueIndex < 0) valueIndex = lineText.indexOf(valueToFind);
            if (valueIndex >= 0) {
                let valueEnd = valueIndex;
                if (lineText[valueIndex] === "'" || lineText[valueIndex] === '"') {
                    valueEnd = lineText.indexOf(lineText[valueIndex], valueIndex + 1) + 1;
                    if (valueEnd === 0) valueEnd = valueIndex + valueToFind.length + 2;
                } else {
                    valueEnd = valueIndex + valueToFind.length;
                }
                return new vscode.Range(line, valueIndex, line, valueEnd);
            }
        }
        const itemMatch = lineText.indexOf(error.item);
        if (itemMatch >= 0) {
            return new vscode.Range(line, itemMatch, line, itemMatch + error.item.length);
        }
        return new vscode.Range(line, 0, line, lineText.length);
    } catch {
        return new vscode.Range(line, 0, line, Number.MAX_VALUE);
    }
}

function buildDiagnosticsFromResult(document: vscode.TextDocument, result: ValidationResult): vscode.Diagnostic[] {
    const diagnostics: vscode.Diagnostic[] = [];
    for (const error of result.errors) {
        const range = errorToRange(document, error);
        const severity =
            error.severity === 'error' ? vscode.DiagnosticSeverity.Error : vscode.DiagnosticSeverity.Warning;
        const d = new vscode.Diagnostic(range, `${error.item}: ${error.message}`, severity);
        d.source = 'PDBe mmCIF Validator';
        d.code = 'mmcif-validator';
        diagnostics.push(d);
    }
    return diagnostics;
}

function scriptFailureToDiagnostic(failure: ScriptFailure): vscode.Diagnostic {
    const range = new vscode.Range(0, 0, 0, Number.MAX_VALUE);
    return new vscode.Diagnostic(range, failure.message, vscode.DiagnosticSeverity.Error);
}

function scriptFailureUserMessage(failure: ScriptFailure): string {
    switch (failure.error_code) {
        case ErrorCode.DICT_NOT_FOUND:
            return 'Dictionary file not found. Please check mmcifValidator.dictionaryPath or dictionary URL.';
        case ErrorCode.CIF_NOT_FOUND:
            return 'mmCIF file not found.';
        case ErrorCode.DOWNLOAD_ERROR:
            return 'Failed to download dictionary. Check your connection and mmcifValidator.dictionaryUrl.';
        default:
            return failure.message;
    }
}

function formatMissingItem(m: DepositionMissingItem): string {
    const row = m.row_index !== undefined ? ` row ${m.row_index + 1}` : '';
    const key = m.row_key !== undefined ? ` (${m.row_key})` : '';
    const err = m.has_validation_error ? ' [validation error]' : '';
    return `${m.item}${row}${key}${err}`;
}

function showDepositionReadiness(dep: MetadataCompleteness, outputChannel: vscode.OutputChannel): void {
    outputChannel.appendLine('');
    outputChannel.appendLine('--- Metadata completeness ---');
    outputChannel.appendLine(`  ${dep.percentage}% (${dep.filled_count}/${dep.total_count} mandatory items filled)`);
    if (dep.method_detected) {
        outputChannel.appendLine(`  Method: ${dep.method_detected}`);
    }
    if (dep.message) {
        outputChannel.appendLine(`  ${dep.message}`);
    }
    const missingCats = dep.missing_categories ?? [];
    const missingItems = dep.missing_items ?? [];
    if (missingCats.length > 0) {
        outputChannel.appendLine('  Missing categories: ' + missingCats.join(', '));
    }
    if (missingItems.length > 0) {
        outputChannel.appendLine('  Missing items:');
        for (const m of missingItems) {
            outputChannel.appendLine('    - ' + formatMissingItem(m));
        }
    }
    outputChannel.appendLine('');
}

function setDepositionStatusBar(dep: MetadataCompleteness, item?: vscode.StatusBarItem): void {
    if (!item) return;
    const methodNote = dep.method_detected ? ` (${dep.method_detected})` : ' (method unknown)';
    item.text = `$(check-all) Metadata: ${dep.percentage}%${methodNote}`;
    const missingCats = dep.missing_categories ?? [];
    const missingItems = dep.missing_items ?? [];
    const parts = [`${dep.filled_count}/${dep.total_count} mandatory items filled`];
    if (dep.message) parts.push(dep.message);
    if (missingCats.length > 0) parts.push(`Missing categories: ${missingCats.join(', ')}`);
    if (missingItems.length > 0) parts.push(`Missing items: ${missingItems.length} (see Output channel or "Metadata Completeness" in Explorer sidebar)`);
    item.tooltip = parts.join('\n');
    item.show();
}

function clearDepositionStatusBar(item?: vscode.StatusBarItem): void {
    if (item) item.hide();
}

/**
 * Update status bar (and keep tree view untouched) from a cached metadata-completeness value.
 * Used when switching between already-validated documents without re-running validation.
 */
export function updateMetadataCompletenessUIFromCache(dep: MetadataCompleteness | null, ctx: ValidationContext): void {
    if (dep) {
        setDepositionStatusBar(dep, ctx.depositionStatusBarItem);
    } else {
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
    }
}

export async function validateDocument(
    document: vscode.TextDocument,
    diagnosticCollection: vscode.DiagnosticCollection,
    ctx: ValidationContext
): Promise<void> {
    const { outputChannel, extensionPath } = ctx;
    const settings = getSettings();
    if (!settings.enabled) {
        diagnosticCollection.delete(document.uri);
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
        ctx.onDepositionUpdate?.(document.uri.toString(), null);
        return;
    }

    const getCachedPath = getCachedDictionaryPath;
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const source = getDictionarySource(workspaceFolder, getCachedPath);
    if (!source) {
        diagnosticCollection.delete(document.uri);
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
        ctx.onDepositionUpdate?.(document.uri.toString(), null);
        return;
    }

    let dictSource = source.dictSource;
    let useUrl = source.useUrl;

    const scriptPath = getScriptPath(extensionPath);
    if (!scriptPath || !fs.existsSync(scriptPath)) {
        outputChannel.appendLine('ERROR: Validation script not found.');
        vscode.window.showErrorMessage(
            'Validation script not found. Please ensure validate_mmcif.py is in the extension or workspace.'
        );
        diagnosticCollection.delete(document.uri);
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
        ctx.onDepositionUpdate?.(document.uri.toString(), null);
        return;
    }

    if (useUrl && dictSource) {
        try {
            const cachedPath = await downloadAndCacheDictionary(dictSource, {
                pythonPath: settings.pythonPath,
                scriptPath,
                outputChannel,
            });
            if (cachedPath) {
                dictSource = cachedPath;
                useUrl = false;
            } else {
                outputChannel.appendLine('Warning: Could not cache dictionary; Python script may download on validate.');
            }
        } catch (err: unknown) {
            outputChannel.appendLine(`Error caching dictionary: ${err instanceof Error ? err.message : String(err)}`);
        }
    }

    outputChannel.appendLine(`Using dictionary: ${dictSource} (URL: ${useUrl})`);

    if (!useUrl && !fs.existsSync(dictSource)) {
        vscode.window.showErrorMessage(`Dictionary file not found: ${dictSource}`);
        diagnosticCollection.delete(document.uri);
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
        ctx.onDepositionUpdate?.(document.uri.toString(), null);
        return;
    }

    const pythonPath = settings.pythonPath;
    const command = useUrl
        ? `"${pythonPath}" "${scriptPath}" --url "${dictSource}" "${document.fileName}"`
        : `"${pythonPath}" "${scriptPath}" --file "${dictSource}" "${document.fileName}"`;

    outputChannel.appendLine(`Running: ${command}`);

    let stdout = '';
    let stderr = '';
    let exitCode: number | undefined;

    try {
        const result = await execAsync(command, { timeout: settings.validationTimeoutMs });
        stdout = result.stdout ?? '';
        stderr = result.stderr ?? '';
    } catch (err: unknown) {
        const execErr = err as { stdout?: string; stderr?: string; code?: number; signal?: string };
        stdout = execErr.stdout ?? '';
        stderr = execErr.stderr ?? '';
        exitCode = execErr.code;
        outputChannel.appendLine(`ERROR: ${execErr instanceof Error ? execErr.message : String(execErr)}`);
        if (stdout) outputChannel.appendLine('--- stdout ---');
        outputChannel.appendLine(stdout);
        if (stderr) outputChannel.appendLine('--- stderr ---');
        outputChannel.appendLine(stderr);

        if (String(execErr.code) === 'ETIMEDOUT' || execErr.signal === 'SIGTERM') {
            vscode.window.showErrorMessage('Validation timed out. The file might be too large.');
            diagnosticCollection.set(document.uri, []);
            return;
        }
    }

    const json = extractJsonFromStdout(stdout);
    let diagnostics: vscode.Diagnostic[] = [];

    if (isScriptFailure(json)) {
        diagnostics = [scriptFailureToDiagnostic(json)];
        vscode.window.showErrorMessage(scriptFailureUserMessage(json));
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
        ctx.onDepositionUpdate?.(document.uri.toString(), null);
    } else if (isValidationResult(json)) {
        diagnostics = buildDiagnosticsFromResult(document, json);
        const dep = (json as ValidationResult).metadata_completeness;
        if (dep) {
            showDepositionReadiness(dep, outputChannel);
            setDepositionStatusBar(dep, ctx.depositionStatusBarItem);
            ctx.onDepositionUpdate?.(document.uri.toString(), dep);
        } else {
            clearDepositionStatusBar(ctx.depositionStatusBarItem);
            ctx.onDepositionUpdate?.(document.uri.toString(), null);
        }
    } else if (exitCode === 1 && stderr) {
        const match = stderr.match(/Error: (.+)/);
        if (match) {
            diagnostics = [
                new vscode.Diagnostic(
                    new vscode.Range(0, 0, 0, Number.MAX_VALUE),
                    match[1],
                    vscode.DiagnosticSeverity.Error
                ),
            ];
        }
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
        ctx.onDepositionUpdate?.(document.uri.toString(), null);
    } else {
        clearDepositionStatusBar(ctx.depositionStatusBarItem);
        ctx.onDepositionUpdate?.(document.uri.toString(), null);
    }

    diagnosticCollection.set(document.uri, diagnostics);

    if (diagnostics.length === 0) {
        vscode.window.setStatusBarMessage('mmCIF validation: No errors', 3000);
    } else {
        const errorCount = diagnostics.filter(d => d.severity === vscode.DiagnosticSeverity.Error).length;
        const warningCount = diagnostics.filter(d => d.severity === vscode.DiagnosticSeverity.Warning).length;
        vscode.window.setStatusBarMessage(
            `mmCIF validation: ${errorCount} error(s), ${warningCount} warning(s)`,
            3000
        );
    }
}
