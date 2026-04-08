/**
 * PDBe mmCIF Validator - Visual Studio Code Extension
 * Entry point: register commands and initialise; validation, hover, config, dictionary live in separate modules.
 *
 * @author Deborah Harrus
 * @organization Protein Data Bank in Europe (PDBe), EMBL-EBI
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import { getSettings, getScriptPath } from './config';
import { getCachedDictionaryPath, downloadAndCacheDictionary } from './dictionary';
import { createHoverProvider } from './hover';
import { validateDocument, updateMetadataCompletenessUIFromCache } from './validation';
import { MetadataCompleteness } from './types';
import { updateDepositionReadiness, registerDepositionView } from './depositionView';
import { CifFoldingRangeProvider } from './folding';
import { CifDocumentSymbolProvider } from './symbols';
import { createLoopLabelDecoration, updateLoopLabels } from './loopLabels';

export function activate(context: vscode.ExtensionContext): void {
    const outputChannel = vscode.window.createOutputChannel('PDBe mmCIF Validator');
    context.subscriptions.push(outputChannel);

    outputChannel.appendLine('PDBe mmCIF Validator extension is now active');

    const diagnosticCollection = vscode.languages.createDiagnosticCollection('mmcif-validator');
    context.subscriptions.push(diagnosticCollection);

    const config = vscode.workspace.getConfiguration('mmcifValidator');
    const dictionaryUrl = config.get<string>('dictionaryUrl', 'http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic');
    const dictionaryPath = config.get<string>('dictionaryPath', '');
    const settings = getSettings();
    const scriptPath = getScriptPath(context.extensionPath);

    if (dictionaryUrl && !dictionaryPath && scriptPath && fs.existsSync(scriptPath)) {
        const cachedPath = getCachedDictionaryPath();
        if (!cachedPath || !fs.existsSync(cachedPath)) {
            downloadAndCacheDictionary(dictionaryUrl, {
                pythonPath: settings.pythonPath,
                scriptPath,
                outputChannel,
            }).catch((err) => {
                outputChannel.appendLine(`Background dictionary download failed: ${err instanceof Error ? err.message : String(err)}`);
            });
        } else {
            const stats = fs.statSync(cachedPath);
            const ageInDays = (Date.now() - stats.mtimeMs) / (1000 * 60 * 60 * 24);
            if (ageInDays >= 30) {
                outputChannel.appendLine(`Dictionary cache is ${ageInDays.toFixed(1)} days old, refreshing...`);
                downloadAndCacheDictionary(dictionaryUrl, {
                    pythonPath: settings.pythonPath,
                    scriptPath,
                    outputChannel,
                }).catch((err) => {
                    outputChannel.appendLine(`Background dictionary refresh failed: ${err instanceof Error ? err.message : String(err)}`);
                });
            } else {
                outputChannel.appendLine(`Using cached dictionary (age: ${ageInDays.toFixed(1)} days)`);
            }
        }
    }

    const metadataByUri = new Map<string, MetadataCompleteness | null>();
    const loopLabelDecoration = createLoopLabelDecoration();
    context.subscriptions.push(loopLabelDecoration);

    const validationCtx = {
        outputChannel,
        extensionPath: context.extensionPath,
        depositionStatusBarItem: vscode.window.createStatusBarItem('mmcif.deposition', vscode.StatusBarAlignment.Right),
        onDepositionUpdate: (uri: string, dep: MetadataCompleteness | null) => {
            metadataByUri.set(uri, dep ?? null);
            updateDepositionReadiness(dep ?? null);
        },
    } as const;
    context.subscriptions.push(validationCtx.depositionStatusBarItem);

    registerDepositionView(context);

    vscode.window.onDidChangeActiveTextEditor((editor) => {
        if (!editor) {
            updateMetadataCompletenessUIFromCache(null, validationCtx);
            updateDepositionReadiness(null);
            return;
        }
        const doc = editor.document;
        if (doc.languageId === 'cif' || doc.fileName.endsWith('.cif')) {
            const key = doc.uri.toString();
            const dep = metadataByUri.get(key) ?? null;
            updateMetadataCompletenessUIFromCache(dep, validationCtx);
            updateDepositionReadiness(dep);
        } else {
            updateMetadataCompletenessUIFromCache(null, validationCtx);
            updateDepositionReadiness(null);
        }
        updateLoopLabels(editor, loopLabelDecoration);
    });

    vscode.workspace.onDidOpenTextDocument((document) => {
        if (document.languageId === 'cif' || document.fileName.endsWith('.cif')) {
            validateDocument(document, diagnosticCollection, validationCtx);
        }
        const activeEditor = vscode.window.activeTextEditor;
        if (activeEditor && activeEditor.document.uri.toString() === document.uri.toString()) {
            updateLoopLabels(activeEditor, loopLabelDecoration);
        }
    });

    vscode.workspace.onDidSaveTextDocument((document) => {
        if (document.languageId === 'cif' || document.fileName.endsWith('.cif')) {
            validateDocument(document, diagnosticCollection, validationCtx);
        }
        const activeEditor = vscode.window.activeTextEditor;
        if (activeEditor && activeEditor.document.uri.toString() === document.uri.toString()) {
            updateLoopLabels(activeEditor, loopLabelDecoration);
        }
    });

    let timeout: NodeJS.Timeout | undefined;
    vscode.workspace.onDidChangeTextDocument((event) => {
        if (event.document.languageId === 'cif' || event.document.fileName.endsWith('.cif')) {
            const activeEditor = vscode.window.activeTextEditor;
            if (activeEditor && activeEditor.document.uri.toString() === event.document.uri.toString()) {
                updateLoopLabels(activeEditor, loopLabelDecoration);
            }
            if (timeout) clearTimeout(timeout);
            timeout = setTimeout(() => {
                validateDocument(event.document, diagnosticCollection, validationCtx);
            }, 1000);
        }
    });

    const validateCommand = vscode.commands.registerCommand('mmcif.validate', () => {
        const editor = vscode.window.activeTextEditor;
        if (editor && (editor.document.languageId === 'cif' || editor.document.fileName.endsWith('.cif'))) {
            validateDocument(editor.document, diagnosticCollection, validationCtx);
        } else {
            vscode.window.showWarningMessage('Please open a .cif file to validate');
        }
    });
    context.subscriptions.push(validateCommand);

    const hoverProvider = vscode.languages.registerHoverProvider('cif', createHoverProvider(outputChannel));
    context.subscriptions.push(hoverProvider);

    const foldingProvider = vscode.languages.registerFoldingRangeProvider('cif', new CifFoldingRangeProvider());
    context.subscriptions.push(foldingProvider);

    const symbolProvider = vscode.languages.registerDocumentSymbolProvider('cif', new CifDocumentSymbolProvider());
    context.subscriptions.push(symbolProvider);

    vscode.workspace.textDocuments.forEach((document) => {
        if (document.languageId === 'cif' || document.fileName.endsWith('.cif')) {
            validateDocument(document, diagnosticCollection, validationCtx);
        }
    });

    updateLoopLabels(vscode.window.activeTextEditor, loopLabelDecoration);
}

export function deactivate(): void {}
