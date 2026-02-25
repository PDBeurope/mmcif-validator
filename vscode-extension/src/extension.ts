/**
 * PDBe mmCIF Validator - Visual Studio Code Extension
 * 
 * @author Deborah Harrus
 * @organization Protein Data Bank in Europe (PDBe), EMBL-EBI
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { exec } from 'child_process';
import { promisify } from 'util';
import { getCifContext } from './cifParser';

const execAsync = promisify(exec);

interface ValidationError {
    line: number;
    item: string;
    message: string;
    severity: string;
    column?: number;
    start_char?: number;
    end_char?: number;
}

interface ValidationResult {
    errors: ValidationError[];
}

let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
    // Create output channel for logging
    outputChannel = vscode.window.createOutputChannel('PDBe mmCIF Validator');
    context.subscriptions.push(outputChannel);
    
    outputChannel.appendLine('PDBe mmCIF Validator extension is now active');
    console.log('PDBe mmCIF Validator extension is now active');

    // Use a unique diagnostic collection name to avoid conflicts
    const diagnosticCollection = vscode.languages.createDiagnosticCollection('mmcif-validator');
    context.subscriptions.push(diagnosticCollection);
    
    // Pre-cache dictionary in background if using default URL
    const config = vscode.workspace.getConfiguration('mmcifValidator');
    const dictionaryUrl = config.get<string>('dictionaryUrl', 'http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic');
    const dictionaryPath = config.get<string>('dictionaryPath', '');
    
    // Only pre-cache if using URL and no local path is set
    if (dictionaryUrl && !dictionaryPath) {
        // Check if we need to download (no cache or cache is old)
        const cachedPath = getCachedDictionaryPath();
        if (!cachedPath || !fs.existsSync(cachedPath)) {
            // Start download in background (don't wait for it)
            downloadAndCacheDictionary(dictionaryUrl).catch((error) => {
                outputChannel.appendLine(`Background dictionary download failed: ${error.message}`);
            });
        } else {
            // Check cache age
            const stats = fs.statSync(cachedPath);
            const ageInDays = (Date.now() - stats.mtimeMs) / (1000 * 60 * 60 * 24);
            if (ageInDays >= 30) { // 1 month = ~30 days
                // Cache is old, refresh in background
                outputChannel.appendLine(`Dictionary cache is ${ageInDays.toFixed(1)} days old, refreshing...`);
                downloadAndCacheDictionary(dictionaryUrl).catch((error) => {
                    outputChannel.appendLine(`Background dictionary refresh failed: ${error.message}`);
                });
            } else {
                outputChannel.appendLine(`Using cached dictionary (age: ${ageInDays.toFixed(1)} days)`);
            }
        }
    }

    // Validate on document open
    vscode.workspace.onDidOpenTextDocument((document) => {
        if (document.languageId === 'cif' || document.fileName.endsWith('.cif')) {
            validateDocument(document, diagnosticCollection, context.extensionPath);
        }
    });

    // Validate on document save
    vscode.workspace.onDidSaveTextDocument((document) => {
        if (document.languageId === 'cif' || document.fileName.endsWith('.cif')) {
            validateDocument(document, diagnosticCollection, context.extensionPath);
        }
    });

    // Validate on document change (debounced)
    let timeout: NodeJS.Timeout | undefined;
    vscode.workspace.onDidChangeTextDocument((event) => {
        if (event.document.languageId === 'cif' || event.document.fileName.endsWith('.cif')) {
            if (timeout) {
                clearTimeout(timeout);
            }
            timeout = setTimeout(() => {
                validateDocument(event.document, diagnosticCollection, context.extensionPath);
            }, 1000);
        }
    });

    // Command to manually validate
    const validateCommand = vscode.commands.registerCommand('mmcif.validate', () => {
        const editor = vscode.window.activeTextEditor;
        if (editor && (editor.document.languageId === 'cif' || editor.document.fileName.endsWith('.cif'))) {
            validateDocument(editor.document, diagnosticCollection, context.extensionPath);
        } else {
            vscode.window.showWarningMessage('Please open a .cif file to validate');
        }
    });

    context.subscriptions.push(validateCommand);

    // Register hover provider to show key and data block information
    /*
     * Hover functionality based on work by Heikki Kainulainen (hmkainul on GitHub)
     * from the vscode-cif extension (https://github.com/hmkainul/vscode-cif)
     * Original work Copyright (c) 2018-2025 Heikki Kainulainen, Kaisa Helttunen
     * Licensed under MIT License
     */
    const hoverProvider = vscode.languages.registerHoverProvider('cif', {
        provideHover(document: vscode.TextDocument, position: vscode.Position) {
            try {
                const line = document.lineAt(position.line);
                const lineText = line.text;
                const char = position.character;
                
                // Check if we're hovering over a value (not a tag, comment, or keyword)
                // Skip if on a tag (starts with _)
                if (char < lineText.length && lineText[char] === '_') {
                    return null;
                }
                
                // Skip if on a comment
                const commentIndex = lineText.indexOf('#');
                if (commentIndex >= 0 && char >= commentIndex) {
                    return null;
                }
                
                // Skip if on keywords like DATA_, LOOP_, etc.
                if (/^(DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)/i.test(lineText.trim())) {
                    return null;
                }
                
                // Get context for this position
                const context = getCifContext(document, position);
                
                // Only show hover if we have a tag (meaning we're on a value)
                if (!context.currentTag) {
                    return null;
                }
                
                // Get the actual value text at the cursor position
                const valueText = getValueAtPosition(document, position);
                
                // Build hover content in the format: data block, key, value
                const hoverLines: string[] = [];
                
                if (context.dataBlock) {
                    hoverLines.push(context.dataBlock);
                }
                
                hoverLines.push(context.currentTag);
                
                if (valueText) {
                    hoverLines.push(valueText);
                }
                
                // Format as code block similar to original extension
                const hoverContent = new vscode.MarkdownString();
                hoverContent.appendCodeblock(hoverLines.join('\n'), 'cif');
                
                return new vscode.Hover(hoverContent);
            } catch (error) {
                // Silently fail - hover is a nice-to-have feature
                outputChannel.appendLine(`Hover error: ${error}`);
            }
            
            return null;
        }
    });
    
    context.subscriptions.push(hoverProvider);

    // Helper function to get the value text at a position
    function getValueAtPosition(document: vscode.TextDocument, position: vscode.Position): string | null {
        try {
            const line = document.lineAt(position.line);
            const lineText = line.text;
            const char = position.character;
            
            // Find the value containing this position
            let start = char;
            let end = char;
            
            // Expand backwards to find start of value
            while (start > 0 && !/\s/.test(lineText[start - 1]) && lineText[start - 1] !== '#') {
                start--;
            }
            
            // Expand forwards to find end of value
            while (end < lineText.length && !/\s/.test(lineText[end]) && lineText[end] !== '#') {
                end++;
            }
            
            // Handle quoted strings
            if (lineText[start] === "'" || lineText[start] === '"') {
                // Find the closing quote
                const quote = lineText[start];
                const closeIndex = lineText.indexOf(quote, start + 1);
                if (closeIndex > 0) {
                    end = closeIndex + 1;
                }
            }
            
            const value = lineText.substring(start, end).trim();
            return value || null;
        } catch (error) {
            return null;
        }
    }

    // Validate all open CIF files
    vscode.workspace.textDocuments.forEach((document) => {
        if (document.languageId === 'cif' || document.fileName.endsWith('.cif')) {
            validateDocument(document, diagnosticCollection, context.extensionPath);
        }
    });
}

function getCachedDictionaryPath(): string | null {
    // Cache dictionary in a temp directory
    const os = require('os');
    const cacheDir = path.join(os.tmpdir(), 'mmcif-validator-cache');
    if (!fs.existsSync(cacheDir)) {
        try {
            fs.mkdirSync(cacheDir, { recursive: true });
        } catch (e) {
            return null;
        }
    }
    return path.join(cacheDir, 'mmcif_pdbx.dic');
}

async function downloadAndCacheDictionary(url: string): Promise<string | null> {
    const https = require('https');
    const http = require('http');
    const cachedPath = getCachedDictionaryPath();
    
    if (!cachedPath) {
        return null;
    }
    
    // Check if cached file exists and is recent (less than 1 month old)
    if (fs.existsSync(cachedPath)) {
        const stats = fs.statSync(cachedPath);
        const ageInDays = (Date.now() - stats.mtimeMs) / (1000 * 60 * 60 * 24);
        // Also check file size - if it's 0 bytes, it's corrupted
        if (ageInDays < 30 && stats.size > 0) { // 1 month = ~30 days
            outputChannel.appendLine(`Using cached dictionary (age: ${ageInDays.toFixed(1)} days, size: ${stats.size} bytes)`);
            return cachedPath;
        } else if (stats.size === 0) {
            outputChannel.appendLine(`Cached dictionary is corrupted (0 bytes), re-downloading...`);
            fs.unlinkSync(cachedPath); // Delete corrupted file
        }
    }
    
    // Download dictionary
    outputChannel.appendLine(`Downloading dictionary from ${url}...`);
    return new Promise((resolve, reject) => {
        const protocol = url.startsWith('https:') ? https : http;
        const file = fs.createWriteStream(cachedPath);
        
        protocol.get(url, (response: any) => {
            // Handle redirects first
            if (response.statusCode === 301 || response.statusCode === 302 || response.statusCode === 307 || response.statusCode === 308) {
                file.close();
                fs.unlink(cachedPath, () => {});
                const redirectUrl = response.headers.location;
                if (redirectUrl) {
                    // Handle relative redirects
                    const fullRedirectUrl = redirectUrl.startsWith('http') 
                        ? redirectUrl 
                        : new URL(redirectUrl, url).toString();
                    outputChannel.appendLine(`Redirecting to: ${fullRedirectUrl}`);
                    downloadAndCacheDictionary(fullRedirectUrl).then(resolve).catch(reject);
                } else {
                    reject(new Error('Redirect without location header'));
                }
                return;
            }
            
            if (response.statusCode !== 200) {
                file.close();
                fs.unlink(cachedPath, () => {}); // Delete partial file
                reject(new Error(`Failed to download dictionary: ${response.statusCode}`));
                return;
            }
            
            response.pipe(file);
            
            file.on('finish', () => {
                file.close();
                // Verify file was written correctly
                const stats = fs.statSync(cachedPath);
                if (stats.size === 0) {
                    fs.unlink(cachedPath, () => {});
                    reject(new Error('Downloaded file is empty'));
                    return;
                }
                outputChannel.appendLine(`Dictionary cached to: ${cachedPath} (${stats.size} bytes)`);
                resolve(cachedPath);
            });
            
            file.on('error', (err: Error) => {
                file.close();
                fs.unlink(cachedPath, () => {}); // Delete partial file
                reject(err);
            });
        }).on('error', (err: Error) => {
            file.close();
            fs.unlink(cachedPath, () => {}); // Delete partial file
            reject(err);
        });
    });
}

async function validateDocument(
    document: vscode.TextDocument,
    diagnosticCollection: vscode.DiagnosticCollection,
    extensionPath?: string
) {
    const config = vscode.workspace.getConfiguration('mmcifValidator');
    
    if (!config.get<boolean>('enabled', true)) {
        diagnosticCollection.delete(document.uri);
        return;
    }

    const dictionaryPath = config.get<string>('dictionaryPath', '');
    const dictionaryUrl = config.get<string>('dictionaryUrl', 'http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic');
    const pythonPath = config.get<string>('pythonPath', 'python');
    const validationTimeoutSeconds = config.get<number>('validationTimeoutSeconds', 60);
    const validationTimeoutMs = Math.max(5000, Math.min(600000, validationTimeoutSeconds * 1000));

    // Determine dictionary source
    let dictSource: string | null = null;
    let useUrl = false;
    
    if (dictionaryUrl) {
        dictSource = dictionaryUrl;
        useUrl = true;
    } else if (dictionaryPath) {
        // Resolve relative paths relative to workspace
        if (path.isAbsolute(dictionaryPath)) {
            dictSource = dictionaryPath;
        } else {
            // Relative path - resolve from workspace root
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (workspaceFolder) {
                dictSource = path.join(workspaceFolder.uri.fsPath, dictionaryPath);
            } else {
                dictSource = dictionaryPath; // Fallback to as-is
            }
        }
    } else {
        // Try to find dictionary in common locations
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (workspaceFolder) {
            const commonNames = ['mmcif_pdbx_v5_next.dic', 'mmcif_pdbx_5408.dic', 'mmcif_pdbx.dic'];
            for (const name of commonNames) {
                const possiblePath = path.join(workspaceFolder.uri.fsPath, name);
                if (fs.existsSync(possiblePath)) {
                    dictSource = possiblePath;
                    break;
                }
            }
        }
    }

    // If no source found, try to find local dictionary first, then use cached or default URL
    if (!dictSource) {
        // Try to find dictionary in common locations
        const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
        if (workspaceFolder) {
            const commonNames = ['mmcif_pdbx_5408.dic', 'mmcif_pdbx_v5_next.dic', 'mmcif_pdbx.dic'];
            for (const name of commonNames) {
                const possiblePath = path.join(workspaceFolder.uri.fsPath, name);
                if (fs.existsSync(possiblePath)) {
                    dictSource = possiblePath;
                    break;
                }
            }
        }
        // If still not found, check for cached dictionary
        if (!dictSource) {
            const cachedDictPath = getCachedDictionaryPath();
            if (cachedDictPath && fs.existsSync(cachedDictPath)) {
                dictSource = cachedDictPath;
                outputChannel.appendLine(`Using cached dictionary: ${cachedDictPath}`);
            } else {
                // Use default URL (will be downloaded and cached)
                dictSource = 'http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic';
                useUrl = true;
            }
        }
    }
    
    // If using URL, try to download and cache it first
    if (useUrl && dictSource) {
        try {
            const cachedPath = await downloadAndCacheDictionary(dictSource);
            if (cachedPath) {
                dictSource = cachedPath;
                useUrl = false;
            } else {
                outputChannel.appendLine('Warning: Could not cache dictionary, Python script will download it');
            }
        } catch (error: any) {
            outputChannel.appendLine(`Error caching dictionary: ${error.message}`);
            outputChannel.appendLine('Falling back to Python script download');
            // Continue with URL - Python script will handle it
        }
    }
    
    // Log dictionary source for debugging
    outputChannel.appendLine(`Using dictionary: ${dictSource} (URL: ${useUrl})`);

    // For URL, we'll pass it directly to the script
    // For file path, check if it exists
    if (!useUrl && !fs.existsSync(dictSource)) {
        vscode.window.showErrorMessage(
            `Dictionary file not found: ${dictSource}. Please check your settings.`
        );
        diagnosticCollection.delete(document.uri);
        return;
    }

    // Get the validation script path
    // Try multiple possible locations
    const possiblePaths = [
        path.join(__dirname, '..', 'python-script', 'validate_mmcif.py'), // From vscode-extension/out to python-script (same extension folder)
        path.join(extensionPath || '', 'python-script', 'validate_mmcif.py'), // Extension path with python-script
        path.join(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '', 'python-script', 'validate_mmcif.py'),
        path.join(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '', 'validate_mmcif.py') // Legacy location
    ];
    
    // Add extension path if available (for packaged extension)
    if (extensionPath) {
        possiblePaths.push(path.join(extensionPath, 'python-script', 'validate_mmcif.py'));
        possiblePaths.push(path.join(extensionPath, 'validate_mmcif.py')); // Legacy location
    }
    
    let scriptPath = possiblePaths.find(p => fs.existsSync(p));
    if (!scriptPath) {
        // Try to find it in workspace
        const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        if (workspacePath) {
            const workspaceScript = path.join(workspacePath, 'validate_mmcif.py');
            if (fs.existsSync(workspaceScript)) {
                scriptPath = workspaceScript;
            }
        }
    }
    
    if (!scriptPath || !fs.existsSync(scriptPath)) {
        const errorMsg = `Validation script not found. Please ensure validate_mmcif.py is in the workspace or extension directory.`;
        outputChannel.appendLine(`ERROR: ${errorMsg}`);
        outputChannel.appendLine(`Searched paths: ${possiblePaths.join(', ')}`);
        vscode.window.showErrorMessage(errorMsg);
        diagnosticCollection.delete(document.uri);
        return;
    }
    
    outputChannel.appendLine(`Using validation script: ${scriptPath}`);

    try {
        // Run validation
        // Build command: python script.py [--file|--url] dict_source cif_file
        let command: string;
        if (useUrl) {
            command = `"${pythonPath}" "${scriptPath}" --url "${dictSource}" "${document.fileName}"`;
        } else {
            command = `"${pythonPath}" "${scriptPath}" --file "${dictSource}" "${document.fileName}"`;
        }
        
        // Log the command for debugging
        outputChannel.appendLine(`Running validation: ${command}`);
        outputChannel.appendLine(`Dictionary: ${dictSource} (URL: ${useUrl})`);
        outputChannel.appendLine(`Script: ${scriptPath}`);
        
        const { stdout, stderr } = await execAsync(
            command,
            { timeout: validationTimeoutMs }
        );
        
        // Log output for debugging
        outputChannel.appendLine('--- Validation Output ---');
        outputChannel.appendLine(stdout);
        if (stderr) {
            outputChannel.appendLine('--- stderr ---');
            outputChannel.appendLine(stderr);
        }

        const diagnostics: vscode.Diagnostic[] = [];

        // Try to parse JSON output (look for JSON object in stdout)
        // JSON is typically at the end, but may be preceded by text output
        const lines = stdout.split('\n');
        let jsonStart = -1;
        let jsonEnd = -1;
        
        // Find JSON block (starts with { and ends with })
        for (let i = 0; i < lines.length; i++) {
            const trimmed = lines[i].trim();
            if (trimmed.startsWith('{') && jsonStart === -1) {
                jsonStart = i;
            }
            if (trimmed === '}' || (trimmed.endsWith('}') && jsonStart >= 0)) {
                jsonEnd = i;
                break;
            }
        }

        if (jsonStart >= 0 && jsonEnd >= jsonStart) {
            try {
                const jsonStr = lines.slice(jsonStart, jsonEnd + 1).join('\n');
                outputChannel.appendLine(`Found JSON output (lines ${jsonStart + 1}-${jsonEnd + 1})`);
                const result: ValidationResult = JSON.parse(jsonStr);
                
                for (const error of result.errors) {
                    const line = Math.max(0, error.line - 1); // Convert to 0-based
                    
                    // Try to find the specific item or value in the line for better highlighting
                    let range: vscode.Range;
                    try {
                        const lineText = document.lineAt(line).text;
                        
                        // Use start_char and end_char if available (most accurate)
                        if (error.start_char !== undefined && error.end_char !== undefined && 
                            error.start_char !== null && error.end_char !== null) {
                            // Use the character positions directly from the validator
                            range = new vscode.Range(
                                line, 
                                error.start_char, 
                                line, 
                                error.end_char
                            );
                        } else {
                            // Fallback: try to find the value or item in the line
                            const valueMatch = error.message.match(/Value '([^']+)'/);
                            if (valueMatch && valueMatch[1]) {
                                // Try to find the value (may be quoted or unquoted)
                                const valueToFind = valueMatch[1];
                                let valueIndex = lineText.indexOf(`'${valueToFind}'`);
                                if (valueIndex < 0) {
                                    valueIndex = lineText.indexOf(`"${valueToFind}"`);
                                }
                                if (valueIndex < 0) {
                                    valueIndex = lineText.indexOf(valueToFind);
                                }
                                if (valueIndex >= 0) {
                                    // Find the end of the value (handle quotes)
                                    let valueEnd = valueIndex;
                                    if (lineText[valueIndex] === "'" || lineText[valueIndex] === '"') {
                                        valueEnd = lineText.indexOf(lineText[valueIndex], valueIndex + 1) + 1;
                                        if (valueEnd === 0) valueEnd = valueIndex + valueToFind.length + 2;
                                    } else {
                                        valueEnd = valueIndex + valueToFind.length;
                                    }
                                    range = new vscode.Range(line, valueIndex, line, valueEnd);
                                } else {
                                    // Fallback: highlight item name
                                    const itemMatch = lineText.indexOf(error.item);
                                    if (itemMatch >= 0) {
                                        range = new vscode.Range(line, itemMatch, line, itemMatch + error.item.length);
                                    } else {
                                        range = new vscode.Range(line, 0, line, lineText.length);
                                    }
                                }
                            } else {
                                // No value in message, highlight item name (e.g., missing mandatory items)
                                const itemMatch = lineText.indexOf(error.item);
                                if (itemMatch >= 0) {
                                    range = new vscode.Range(line, itemMatch, line, itemMatch + error.item.length);
                                } else {
                                    range = new vscode.Range(line, 0, line, lineText.length);
                                }
                            }
                        }
                    } catch (e) {
                        // If line doesn't exist, use a safe range
                        range = new vscode.Range(line, 0, line, Number.MAX_VALUE);
                    }

                    const severity = error.severity === 'error' 
                        ? vscode.DiagnosticSeverity.Error 
                        : vscode.DiagnosticSeverity.Warning;

                    const diagnostic = new vscode.Diagnostic(
                        range,
                        `${error.item}: ${error.message}`,
                        severity
                    );
                    diagnostic.source = 'PDBe mmCIF Validator';
                    diagnostic.code = 'mmcif-validator'; // Add code to identify our diagnostics
                    diagnostics.push(diagnostic);
                }
            } catch (parseError) {
                // If JSON parsing fails, try to parse text output
                outputChannel.appendLine(`Failed to parse JSON output: ${parseError}`);
                console.error('Failed to parse JSON output:', parseError);
            }
        } else {
            outputChannel.appendLine('No JSON output found in validation result');
            // Check if validation passed
            if (stdout.includes('Validation passed')) {
                outputChannel.appendLine('Validation passed - no errors found');
            }
        }

        // If no JSON found, check for errors in stderr
        if (diagnostics.length === 0 && stderr) {
            const errorMatch = stderr.match(/Error: (.+)/);
            if (errorMatch) {
                const range = new vscode.Range(0, 0, 0, Number.MAX_VALUE);
                const diagnostic = new vscode.Diagnostic(
                    range,
                    errorMatch[1],
                    vscode.DiagnosticSeverity.Error
                );
                diagnostic.source = 'mmCIF Validator';
                diagnostics.push(diagnostic);
            }
        }

        // Always set diagnostics (even if empty) to clear previous results
        // This ensures the editor shows current validation state
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

    } catch (error: any) {
        outputChannel.appendLine(`ERROR: ${error.message}`);
        outputChannel.appendLine(`Error code: ${error.code}`);
        if (error.stdout) {
            outputChannel.appendLine('--- stdout from error ---');
            outputChannel.appendLine(error.stdout);
        }
        if (error.stderr) {
            outputChannel.appendLine('--- stderr from error ---');
            outputChannel.appendLine(error.stderr);
        }
        console.error('Validation error:', error);
        
        // Check if it's a timeout
        if (error.code === 'ETIMEDOUT' || error.signal === 'SIGTERM') {
            vscode.window.showErrorMessage('Validation timed out. The file might be too large.');
        } else if (error.code === 1 || (error as any).exitCode === 1) {
            // Exit code 1 means validation found errors - this is expected
            // The errors should be in stdout
            const stdout = error.stdout || '';
            if (stdout) {
                outputChannel.appendLine('--- Parsing validation errors from stdout ---');
                // Try to parse errors from stdout using the same logic as the try block
                const lines = stdout.split('\n');
                let jsonStart = -1;
                
                // Find JSON block start (look for opening brace)
                for (let i = 0; i < lines.length; i++) {
                    const trimmed = lines[i].trim();
                    if (trimmed.startsWith('{')) {
                        jsonStart = i;
                        break;
                    }
                }
                
                if (jsonStart >= 0) {
                    try {
                        // Try to extract complete JSON by finding matching braces
                        // Start from the opening brace and find the matching closing brace
                        let braceCount = 0;
                        let jsonEnd = jsonStart;
                        for (let i = jsonStart; i < lines.length; i++) {
                            const line = lines[i];
                            for (const char of line) {
                                if (char === '{') braceCount++;
                                if (char === '}') braceCount--;
                                if (braceCount === 0 && i >= jsonStart) {
                                    jsonEnd = i;
                                    break;
                                }
                            }
                            if (braceCount === 0) break;
                        }
                        
                        // Extract JSON string
                        const jsonStr = lines.slice(jsonStart, jsonEnd + 1).join('\n').trim();
                        outputChannel.appendLine(`Found JSON output in error (lines ${jsonStart + 1}-${jsonEnd + 1})`);
                        outputChannel.appendLine(`JSON string length: ${jsonStr.length}`);
                        
                        const result: ValidationResult = JSON.parse(jsonStr);
                        const diagnostics: vscode.Diagnostic[] = [];
                        
                        for (const err of result.errors) {
                            const line = Math.max(0, err.line - 1);
                            
                            // Try to find the specific item or value in the line for better highlighting
                            let range: vscode.Range;
                            try {
                                const lineText = document.lineAt(line).text;
                                
                                // Use start_char and end_char if available (most accurate)
                                if (err.start_char !== undefined && err.end_char !== undefined && 
                                    err.start_char !== null && err.end_char !== null) {
                                    // Use the character positions directly from the validator
                                    range = new vscode.Range(
                                        line, 
                                        err.start_char, 
                                        line, 
                                        err.end_char
                                    );
                                } else {
                                    // Fallback: try to find the value or item in the line
                                    const valueMatch = err.message.match(/Value '([^']+)'/);
                                    if (valueMatch && valueMatch[1]) {
                                        // Try to find the value (may be quoted or unquoted)
                                        const valueToFind = valueMatch[1];
                                        let valueIndex = lineText.indexOf(`'${valueToFind}'`);
                                        if (valueIndex < 0) {
                                            valueIndex = lineText.indexOf(`"${valueToFind}"`);
                                        }
                                        if (valueIndex < 0) {
                                            valueIndex = lineText.indexOf(valueToFind);
                                        }
                                        if (valueIndex >= 0) {
                                            // Find the end of the value (handle quotes)
                                            let valueEnd = valueIndex;
                                            if (lineText[valueIndex] === "'" || lineText[valueIndex] === '"') {
                                                valueEnd = lineText.indexOf(lineText[valueIndex], valueIndex + 1) + 1;
                                                if (valueEnd === 0) valueEnd = valueIndex + valueToFind.length + 2;
                                            } else {
                                                valueEnd = valueIndex + valueToFind.length;
                                            }
                                            range = new vscode.Range(line, valueIndex, line, valueEnd);
                                        } else {
                                            // Fallback: highlight item name
                                            const itemMatch = lineText.indexOf(err.item);
                                            if (itemMatch >= 0) {
                                                range = new vscode.Range(line, itemMatch, line, itemMatch + err.item.length);
                                            } else {
                                                range = new vscode.Range(line, 0, line, lineText.length);
                                            }
                                        }
                                    } else {
                                        // No value in message, highlight item name (e.g., missing mandatory items)
                                        const itemMatch = lineText.indexOf(err.item);
                                        if (itemMatch >= 0) {
                                            range = new vscode.Range(line, itemMatch, line, itemMatch + err.item.length);
                                        } else {
                                            range = new vscode.Range(line, 0, line, lineText.length);
                                        }
                                    }
                                }
                            } catch (e) {
                                range = new vscode.Range(line, 0, line, Number.MAX_VALUE);
                            }
                            
                            const severity = err.severity === 'error' 
                                ? vscode.DiagnosticSeverity.Error 
                                : vscode.DiagnosticSeverity.Warning;
                            const diagnostic = new vscode.Diagnostic(
                                range,
                                `${err.item}: ${err.message}`,
                                severity
                            );
                            diagnostic.source = 'PDBe mmCIF Validator';
                            diagnostic.code = 'mmcif-validator';
                            diagnostics.push(diagnostic);
                        }
                        
                        // Always set diagnostics (even if empty) to clear previous results
                        diagnosticCollection.set(document.uri, diagnostics);
                        
                        if (diagnostics.length > 0) {
                            const errorCount = diagnostics.filter(d => d.severity === vscode.DiagnosticSeverity.Error).length;
                            const warningCount = diagnostics.filter(d => d.severity === vscode.DiagnosticSeverity.Warning).length;
                            vscode.window.setStatusBarMessage(
                                `mmCIF validation: ${errorCount} error(s), ${warningCount} warning(s)`,
                                3000
                            );
                        }
                    } catch (parseError) {
                        outputChannel.appendLine(`Failed to parse error output: ${parseError}`);
                        console.error('Failed to parse error output:', parseError);
                    }
                } else {
                    outputChannel.appendLine('No JSON output found in error stdout');
                }
            }
        } else {
            vscode.window.showErrorMessage(
                `Validation failed: ${error.message}. Make sure Python is installed and the validation script is accessible.`
            );
        }
    }
}

export function deactivate() {}

