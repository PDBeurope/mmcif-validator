import * as vscode from 'vscode';

const STRUCTURAL_KEYWORD_RE = /^(?:DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)\b/i;

function extractCategoryFromTag(tag: string): string | null {
    const trimmed = tag.trim();
    if (!trimmed.startsWith('_')) {
        return null;
    }
    const withoutUnderscore = trimmed.slice(1);
    const dotIdx = withoutUnderscore.indexOf('.');
    return dotIdx > 0 ? withoutUnderscore.slice(0, dotIdx) : withoutUnderscore || null;
}

function firstLoopCategory(document: vscode.TextDocument, loopStartLine: number): string | null {
    for (let i = loopStartLine + 1; i < document.lineCount; i++) {
        const text = document.lineAt(i).text.trim();
        if (!text || text.startsWith('#')) {
            continue;
        }
        if (STRUCTURAL_KEYWORD_RE.test(text)) {
            return null;
        }
        if (text.startsWith('_')) {
            const tag = text.split(/\s+/)[0];
            return extractCategoryFromTag(tag);
        }
        // Reached data rows before a tag.
        return null;
    }
    return null;
}

export function createLoopLabelDecoration(): vscode.TextEditorDecorationType {
    return vscode.window.createTextEditorDecorationType({
        after: {
            color: new vscode.ThemeColor('descriptionForeground'),
            margin: '0 0 0 0.6em',
        },
        rangeBehavior: vscode.DecorationRangeBehavior.ClosedClosed,
    });
}

export function updateLoopLabels(
    editor: vscode.TextEditor | undefined,
    decoration: vscode.TextEditorDecorationType
): void {
    if (!editor) {
        return;
    }
    const doc = editor.document;
    if (doc.languageId !== 'cif' && !doc.fileName.endsWith('.cif')) {
        editor.setDecorations(decoration, []);
        return;
    }

    const items: vscode.DecorationOptions[] = [];
    for (let i = 0; i < doc.lineCount; i++) {
        const text = doc.lineAt(i).text.trim();
        if (!/^LOOP_\b/i.test(text)) {
            continue;
        }
        const category = firstLoopCategory(doc, i);
        if (!category) {
            continue;
        }

        const loopRaw = doc.lineAt(i).text;
        const loopMatch = loopRaw.match(/loop_/i);
        const startChar = loopMatch ? loopMatch.index ?? 0 : 0;
        const endChar = startChar + 5;
        items.push({
            range: new vscode.Range(i, startChar, i, endChar),
            renderOptions: {
                after: {
                    contentText: `${category}`,
                },
            },
        });
    }

    editor.setDecorations(decoration, items);
}

