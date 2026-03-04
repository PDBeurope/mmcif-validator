/**
 * Hover provider for CIF: shows data block, tag, and value at cursor.
 * Based on work by Heikki Kainulainen (hmkainul) from vscode-cif.
 */

import * as vscode from 'vscode';
import { getCifContext } from './cifParser';

export function getValueAtPosition(document: vscode.TextDocument, position: vscode.Position): string | null {
    try {
        const line = document.lineAt(position.line);
        const lineText = line.text;
        const char = position.character;

        let start = char;
        let end = char;

        while (start > 0 && !/\s/.test(lineText[start - 1]) && lineText[start - 1] !== '#') {
            start--;
        }
        while (end < lineText.length && !/\s/.test(lineText[end]) && lineText[end] !== '#') {
            end++;
        }

        if (lineText[start] === "'" || lineText[start] === '"') {
            const quote = lineText[start];
            const closeIndex = lineText.indexOf(quote, start + 1);
            if (closeIndex > 0) end = closeIndex + 1;
        }

        const value = lineText.substring(start, end).trim();
        return value || null;
    } catch {
        return null;
    }
}

export function createHoverProvider(outputChannel: vscode.OutputChannel): vscode.HoverProvider {
    return {
        provideHover(document: vscode.TextDocument, position: vscode.Position) {
            try {
                const line = document.lineAt(position.line);
                const lineText = line.text;
                const char = position.character;

                if (char < lineText.length && lineText[char] === '_') return null;

                const commentIndex = lineText.indexOf('#');
                if (commentIndex >= 0 && char >= commentIndex) return null;

                if (/^(DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)/i.test(lineText.trim())) return null;

                const context = getCifContext(document, position);
                if (!context.currentTag) return null;

                const valueText = getValueAtPosition(document, position);
                const hoverLines: string[] = [];
                if (context.dataBlock) hoverLines.push(context.dataBlock);
                hoverLines.push(context.currentTag);
                if (valueText) hoverLines.push(valueText);

                const hoverContent = new vscode.MarkdownString();
                hoverContent.appendCodeblock(hoverLines.join('\n'), 'cif');
                return new vscode.Hover(hoverContent);
            } catch (error) {
                outputChannel.appendLine(`Hover error: ${error}`);
            }
            return null;
        },
    };
}
