/*
 * CIF Parser for hover functionality
 * 
 * This file is based on the parser implementation by Heikki Kainulainen (hmkainul on GitHub)
 * from the vscode-cif extension (https://github.com/hmkainul/vscode-cif)
 * 
 * Original work Copyright (c) 2018-2025 Heikki Kainulainen, Kaisa Helttunen
 * Licensed under MIT License
 * 
 * Adapted for use in PDBe mmCIF Validator extension
 */

import * as vscode from 'vscode';

export interface CifContext {
    dataBlock: string | null;
    currentTag: string | null;
}

/**
 * Get the CIF context (data block and tag) for a given position in the document
 * Simplified version that works line-by-line
 */
export function getCifContext(document: vscode.TextDocument, position: vscode.Position): CifContext {
    try {
        const context: CifContext = {
            dataBlock: null,
            currentTag: null
        };
        
        const text = document.getText();
        const lines = text.split(/\r?\n/);
        const currentLine = position.line;
        const currentChar = position.character;
        
        // Find the current data block (search backwards from current line)
        for (let i = currentLine; i >= 0; i--) {
            const line = lines[i];
            const dataMatch = line.match(/^DATA_(\S+)/i);
            if (dataMatch) {
                context.dataBlock = dataMatch[0];
                break;
            }
        }
        
        // Find if we're in a loop and get loop tags
        let inLoop = false;
        let loopStartLine = -1;
        const loopTags: string[] = [];
        
        // Check if current line is a tag line
        const currentLineTrimmed = lines[currentLine].trim();
        const currentLineIsTag = currentLineTrimmed.startsWith('_');
        let currentTag: string | null = null;
        if (currentLineIsTag) {
            const tagMatch = currentLineTrimmed.match(/^(_\S+)/);
            if (tagMatch) {
                currentTag = tagMatch[1];
            }
        }
        
        // Search backwards to find the most recent loop
        for (let i = currentLine; i >= 0; i--) {
            const line = lines[i].trim();
            
            // Check for LOOP_
            if (/^LOOP_/i.test(line)) {
                loopStartLine = i;
                // Collect loop tags
                for (let j = i + 1; j < lines.length; j++) {
                    const tagLine = lines[j].trim();
                    
                    // Stop collecting tags when we hit values (non-tag, non-comment, non-keyword line)
                    if (tagLine && !tagLine.startsWith('_') && !tagLine.startsWith('#') && 
                        !/^(DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)/i.test(tagLine)) {
                        // Found first value line - loop values start here
                        // If current line is a tag that's not in loop tags, we're past the loop
                        if (currentLineIsTag && currentTag && !loopTags.includes(currentTag)) {
                            inLoop = false;
                        } else if (!currentLineIsTag) {
                            // Current line is a value - check if we're still in loop
                            // Look backwards to see if we've passed any non-loop tags
                            let stillInLoop = true;
                            for (let k = currentLine; k >= j; k--) {
                                const checkLine = lines[k].trim();
                                if (checkLine.startsWith('_')) {
                                    const checkTagMatch = checkLine.match(/^(_\S+)/);
                                    if (checkTagMatch && !loopTags.includes(checkTagMatch[1])) {
                                        stillInLoop = false;
                                        break;
                                    }
                                }
                            }
                            inLoop = stillInLoop;
                        } else {
                            inLoop = true;
                        }
                        break;
                    }
                    
                    // Collect tags
                    const tagMatch = tagLine.match(/^(_\S+)/);
                    if (tagMatch) {
                        loopTags.push(tagMatch[1]);
                    }
                }
                break;
            }
            
            // Check for DATA block (loop ends at data block)
            if (/^DATA_/i.test(line)) {
                break;
            }
        }
        
        // Now find the tag for the current position
        if (inLoop && loopTags.length > 0) {
            const tag = findLoopTagAtPosition(lines, loopStartLine, loopTags, currentLine, currentChar);
            if (tag) {
                context.currentTag = tag;
                return context;
            }
        } else {
            // Not in a loop - look for tag on current line or previous lines
            const currentLineText = lines[currentLine];
            const currentLineTrimmed = currentLineText.trim();
            
            // First, try to find a tag on the current line before the cursor
            // Search from the beginning of the line up to the cursor position
            const textBeforeCursor = currentLineText.substring(0, currentChar);
            const tagMatchInLine = textBeforeCursor.match(/(_\S+)(?=\s|$)/);
            
            if (tagMatchInLine) {
                // Found a tag before cursor on current line - use it
                context.currentTag = tagMatchInLine[1];
                return context;
            }
            
            // If no tag found on current line before cursor, search backwards through previous lines
            // Find the most recent tag (simple approach: just find any tag going backwards)
            for (let lineOffset = 1; lineOffset <= 10 && currentLine >= lineOffset; lineOffset++) {
                const checkLine = lines[currentLine - lineOffset];
                if (!checkLine) continue;
                
                const checkLineTrimmed = checkLine.trim();
                
                // Skip empty lines and comments
                if (!checkLineTrimmed || checkLineTrimmed.startsWith('#')) {
                    continue;
                }
                
                // Stop if we hit a DATA block or another structural element
                if (/^(DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)/i.test(checkLineTrimmed)) {
                    break;
                }
                
                // Check if line starts with a tag
                const tagMatch = checkLineTrimmed.match(/^(_\S+)/);
                if (tagMatch) {
                    // Found a tag - use it (don't worry about whether it has a value or not)
                    context.currentTag = tagMatch[1];
                    return context;
                }
            }
        }
        
        return context;
    } catch (error) {
        // Return empty context on error
        return {
            dataBlock: null,
            currentTag: null
        };
    }
}

interface ValueRange {
    start: number;
    end: number;
}

function isStructuralKeyword(line: string): boolean {
    return /^(DATA_|LOOP_|SAVE_|GLOBAL_|STOP_)/i.test(line.trim());
}

function isLoopTagLine(line: string): boolean {
    const trimmed = line.trim();
    return trimmed.startsWith('_');
}

/**
 * Semicolon-delimited CIF text fields start and end with ';' as the first
 * character of a line (STAR/CIF spec). Continuation lines and the closing
 * ';' are part of that one value, not additional loop tokens.
 */
function isSemicolonTextLine(line: string): boolean {
    return line.length > 0 && line[0] === ';';
}

function tagAtCount(loopTags: string[], valueCount: number): string {
    return loopTags[((valueCount % loopTags.length) + loopTags.length) % loopTags.length];
}

function valuesAfterClosingSemicolon(line: string): ValueRange[] {
    // Tokens after the closing ';' on the same line are further loop values.
    const rest = extractValuesFromLine(line.slice(1));
    return rest.map((value) => ({ start: value.start + 1, end: value.end + 1 }));
}

/**
 * Map a cursor position in a loop to the loop tag for that value.
 * Counts semicolon-delimited text fields as a single value, matching gemmi.
 */
export function findLoopTagAtPosition(
    lines: string[],
    loopStartLine: number,
    loopTags: string[],
    currentLine: number,
    currentChar: number
): string | null {
    if (loopTags.length === 0) {
        return null;
    }

    let valueCount = 0;
    let inSemicolonText = false;

    for (let i = loopStartLine + 1; i <= currentLine; i++) {
        const line = lines[i] ?? '';
        const onCurrentLine = i === currentLine;

        if (inSemicolonText) {
            if (isSemicolonTextLine(line)) {
                // Closing ';' ends the text field already counted at the opener.
                inSemicolonText = false;
                if (onCurrentLine) {
                    if (currentChar <= 0) {
                        return tagAtCount(loopTags, valueCount - 1);
                    }
                    const trailing = valuesAfterClosingSemicolon(line);
                    for (const value of trailing) {
                        if (value.start <= currentChar && value.end >= currentChar) {
                            return tagAtCount(loopTags, valueCount);
                        }
                        valueCount++;
                    }
                    return null;
                }
                valueCount += valuesAfterClosingSemicolon(line).length;
                continue;
            }

            // Continuation line of the current semicolon-delimited value.
            if (onCurrentLine) {
                return tagAtCount(loopTags, valueCount - 1);
            }
            continue;
        }

        if (!line.trim() || isLoopTagLine(line) || line.trim().startsWith('#') || isStructuralKeyword(line)) {
            continue;
        }

        if (isSemicolonTextLine(line)) {
            if (onCurrentLine) {
                return tagAtCount(loopTags, valueCount);
            }
            valueCount++;
            inSemicolonText = true;
            continue;
        }

        const values = extractValuesFromLine(line);
        if (onCurrentLine) {
            for (const value of values) {
                if (value.start <= currentChar && value.end >= currentChar) {
                    return tagAtCount(loopTags, valueCount);
                }
                valueCount++;
            }
            return null;
        }
        valueCount += values.length;
    }

    return null;
}

function extractValuesFromLine(line: string): ValueRange[] {
    const values: ValueRange[] = [];
    let pos = 0;
    
    while (pos < line.length) {
        // Skip whitespace
        while (pos < line.length && /\s/.test(line[pos])) {
            pos++;
        }
        if (pos >= line.length) break;
        
        // Skip comments
        if (line[pos] === '#') break;
        
        const start = pos;
        let end = pos;
        
        // Single quoted string
        if (line[pos] === "'") {
            const match = line.substring(pos).match(/^'([^']|'(?!\s|$))*'(?!\S)/);
            if (match) {
                end = pos + match[0].length;
            } else {
                // Unclosed quote - take to end or space
                const spaceIndex = line.indexOf(' ', pos + 1);
                end = spaceIndex > 0 ? spaceIndex : line.length;
            }
        }
        // Double quoted string
        else if (line[pos] === '"') {
            const match = line.substring(pos).match(/^"([^"]|"(?!\s|$))*"(?!\S)/);
            if (match) {
                end = pos + match[0].length;
            } else {
                const spaceIndex = line.indexOf(' ', pos + 1);
                end = spaceIndex > 0 ? spaceIndex : line.length;
            }
        }
        // Unquoted value. A ';' here is an ordinary token; semicolon-delimited
        // text fields are handled by findLoopTagAtPosition (must start at column 0).
        else {
            const spaceIndex = line.indexOf(' ', pos);
            const commentIndex = line.indexOf('#', pos);
            if (spaceIndex > 0 && (commentIndex < 0 || spaceIndex < commentIndex)) {
                end = spaceIndex;
            } else if (commentIndex > 0) {
                end = commentIndex;
            } else {
                end = line.length;
            }
        }
        
        if (end > start) {
            values.push({ start, end });
            pos = end;
        } else {
            pos++;
        }
    }
    
    return values;
}
