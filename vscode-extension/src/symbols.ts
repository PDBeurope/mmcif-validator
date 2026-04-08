import * as vscode from 'vscode';

const STRUCTURAL_KEYWORD_RE = /^(?:DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)\b/i;

function firstLoopTag(document: vscode.TextDocument, loopStartLine: number, loopEndLine: number): string | null {
    for (let i = loopStartLine + 1; i <= loopEndLine; i++) {
        const text = document.lineAt(i).text.trim();
        if (!text || text.startsWith('#')) {
            continue;
        }
        if (text.startsWith('_')) {
            return text.split(/\s+/)[0];
        }
        if (STRUCTURAL_KEYWORD_RE.test(text)) {
            break;
        }
        // First data row reached; tag section ended.
        break;
    }
    return null;
}

/**
 * Document symbols for CIF loops to improve outline and sticky-scroll context.
 */
export class CifDocumentSymbolProvider implements vscode.DocumentSymbolProvider {
    provideDocumentSymbols(
        document: vscode.TextDocument,
        _token: vscode.CancellationToken
    ): vscode.ProviderResult<vscode.SymbolInformation[] | vscode.DocumentSymbol[]> {
        const symbols: vscode.DocumentSymbol[] = [];
        const lineCount = document.lineCount;

        for (let i = 0; i < lineCount; i++) {
            const lineText = document.lineAt(i).text.trim();
            if (!/^LOOP_\b/i.test(lineText)) {
                continue;
            }

            let end = lineCount - 1;
            for (let j = i + 1; j < lineCount; j++) {
                const nextText = document.lineAt(j).text.trim();
                if (STRUCTURAL_KEYWORD_RE.test(nextText)) {
                    end = j - 1;
                    break;
                }
            }

            while (end > i && document.lineAt(end).text.trim() === '') {
                end--;
            }
            if (end <= i) {
                continue;
            }

            const tag = firstLoopTag(document, i, end);
            const name = tag ? `loop_ ${tag}` : 'loop_';
            const fullRange = new vscode.Range(i, 0, end, document.lineAt(end).text.length);
            const selectionRange = new vscode.Range(i, 0, i, document.lineAt(i).text.length);
            symbols.push(new vscode.DocumentSymbol(name, '', vscode.SymbolKind.Namespace, fullRange, selectionRange));
        }

        return symbols;
    }
}

