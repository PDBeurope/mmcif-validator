import * as vscode from 'vscode';

const STRUCTURAL_KEYWORD_RE = /^(?:DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)\b/i;

/**
 * Folding ranges for CIF loop_ blocks.
 * A loop starts at a line containing LOOP_ and ends before the next structural keyword or EOF.
 */
export class CifFoldingRangeProvider implements vscode.FoldingRangeProvider {
    provideFoldingRanges(
        document: vscode.TextDocument,
        _context: vscode.FoldingContext,
        _token: vscode.CancellationToken
    ): vscode.ProviderResult<vscode.FoldingRange[]> {
        const ranges: vscode.FoldingRange[] = [];
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

            if (end > i) {
                ranges.push(new vscode.FoldingRange(i, end, vscode.FoldingRangeKind.Region));
            }
        }

        return ranges;
    }
}

