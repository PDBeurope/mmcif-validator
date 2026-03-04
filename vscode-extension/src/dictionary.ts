/**
 * Dictionary cache path and download (delegated to Python script for single implementation).
 */

import * as path from 'path';
import * as fs from 'fs';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

const CACHE_DIR_NAME = 'mmcif-validator-cache';
const CACHE_FILENAME = 'mmcif_pdbx.dic';

export function getCachedDictionaryPath(): string | null {
    const os = require('os');
    const cacheDir = path.join(os.tmpdir(), CACHE_DIR_NAME);
    if (!fs.existsSync(cacheDir)) {
        try {
            fs.mkdirSync(cacheDir, { recursive: true });
        } catch {
            return null;
        }
    }
    return path.join(cacheDir, CACHE_FILENAME);
}

export interface DownloadOptions {
    pythonPath: string;
    scriptPath: string;
    outputChannel: { appendLine: (s: string) => void };
}

/**
 * Download dictionary via Python script (single implementation shared with CLI).
 * Returns path to cached file or null on failure.
 */
export async function downloadAndCacheDictionary(
    url: string,
    options: DownloadOptions
): Promise<string | null> {
    const { pythonPath, scriptPath, outputChannel } = options;
    const cachedPath = getCachedDictionaryPath();
    if (!cachedPath) return null;

    if (fs.existsSync(cachedPath)) {
        const stats = fs.statSync(cachedPath);
        const ageInDays = (Date.now() - stats.mtimeMs) / (1000 * 60 * 60 * 24);
        if (ageInDays < 30 && stats.size > 0) {
            outputChannel.appendLine(`Using cached dictionary (age: ${ageInDays.toFixed(1)} days, size: ${stats.size} bytes)`);
            return cachedPath;
        }
        if (stats.size === 0) {
            outputChannel.appendLine('Cached dictionary is corrupted (0 bytes), re-downloading...');
            fs.unlinkSync(cachedPath);
        }
    }

    outputChannel.appendLine(`Downloading dictionary from ${url}... (via Python script)`);
    try {
        const command = `"${pythonPath}" "${scriptPath}" download-dictionary --url "${url}"`;
        const { stdout } = await execAsync(command, { timeout: 120000 });
        const lines = stdout.split('\n');
        for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith('{')) {
                const obj = JSON.parse(trimmed);
                if (obj.path) {
                    outputChannel.appendLine(`Dictionary cached to: ${obj.path}`);
                    return obj.path;
                }
                if (obj.success === false && obj.message) {
                    outputChannel.appendLine(`Download failed: ${obj.message}`);
                    return null;
                }
            }
        }
        outputChannel.appendLine('No path in download output');
        return null;
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        outputChannel.appendLine(`Error caching dictionary: ${message}`);
        return null;
    }
}
