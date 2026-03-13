/**
 * Metadata Completeness sidebar view: tree of summary, missing categories, and missing items.
 */

import * as vscode from 'vscode';
import { MetadataCompleteness, DepositionMissingItem } from './types';

type DepositionTreeItem = SummaryItem | MissingCategoriesItem | MissingCategoryItem | MissingItemsItem | MissingItemLeaf;

class SummaryItem extends vscode.TreeItem {
    constructor(public readonly dep: MetadataCompleteness) {
        super(
            `Metadata: ${dep.percentage}% (${dep.filled_count}/${dep.total_count})`,
            vscode.TreeItemCollapsibleState.None
        );
        this.description = dep.method_detected ?? 'method unknown';
        this.tooltip = dep.message ?? undefined;
    }
}

class MissingCategoriesItem extends vscode.TreeItem {
    constructor(count: number) {
        super(`Missing categories (${count})`, count > 0 ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    }
}

class MissingCategoryItem extends vscode.TreeItem {
    constructor(public readonly category: string) {
        super(category, vscode.TreeItemCollapsibleState.None);
        this.contextValue = 'missingCategory';
    }
}

class MissingItemsItem extends vscode.TreeItem {
    constructor(count: number) {
        super(`Missing items (${count})`, count > 0 ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    }
}

function formatMissingItemLabel(m: DepositionMissingItem): string {
    const row = m.row_index !== undefined ? ` row ${m.row_index + 1}` : '';
    const key = m.row_key !== undefined ? ` [${m.row_key}]` : '';
    const err = m.has_validation_error ? ' (validation error)' : '';
    return `${m.item}${row}${key}${err}`;
}

class MissingItemLeaf extends vscode.TreeItem {
    constructor(public readonly missing: DepositionMissingItem) {
        super(formatMissingItemLabel(missing), vscode.TreeItemCollapsibleState.None);
        this.description = missing.category;
        this.contextValue = 'missingItem';
    }
}

let lastDeposition: MetadataCompleteness | null = null;
const changeEmitter = new vscode.EventEmitter<DepositionTreeItem | undefined | null>();
let subscription: vscode.Disposable | undefined;

export function updateDepositionReadiness(dep: MetadataCompleteness | null): void {
    lastDeposition = dep;
    changeEmitter.fire(null);
}

export class DepositionTreeDataProvider implements vscode.TreeDataProvider<DepositionTreeItem> {
    readonly onDidChangeTreeData = changeEmitter.event;

    getTreeItem(element: DepositionTreeItem): vscode.TreeItem {
        return element;
    }

    getChildren(element?: DepositionTreeItem): DepositionTreeItem[] {
        if (!lastDeposition) {
            return [];
        }
        const dep = lastDeposition;
        const missingCats = dep.missing_categories ?? [];
        const missingItems = dep.missing_items ?? [];

        if (!element) {
            const nodes: DepositionTreeItem[] = [
                new SummaryItem(dep),
            ];
            if (missingCats.length > 0) {
                nodes.push(new MissingCategoriesItem(missingCats.length));
            }
            if (missingItems.length > 0) {
                nodes.push(new MissingItemsItem(missingItems.length));
            }
            return nodes;
        }

        if (element instanceof MissingCategoriesItem) {
            return missingCats.map((c) => new MissingCategoryItem(c));
        }
        if (element instanceof MissingItemsItem) {
            return missingItems.map((m) => new MissingItemLeaf(m));
        }

        return [];
    }
}

export function registerDepositionView(context: vscode.ExtensionContext): void {
    const provider = new DepositionTreeDataProvider();
    subscription = vscode.window.registerTreeDataProvider('mmcifDeposition', provider);
    context.subscriptions.push(subscription);
}
