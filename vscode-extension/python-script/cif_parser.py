"""
mmCIF file parser.
"""

from pathlib import Path
from typing import Dict, List, Set, Tuple

from mmcif_types import ItemValue


class MmCIFParser:
    """Parses mmCIF files."""
    
    def __init__(self, cif_path: Path):
        self.cif_path = cif_path
        self.items: Dict[str, List[ItemValue]] = {}  # item_name -> list of ItemValue(line_num, value, global_column_index, local_column_index)
        self.categories: Set[str] = set()  # Set of category names present in the file
        self.lines: List[str] = []
        # Each loop block: (loop_start_line, category_name, [(item_name, header_line_num), ...])
        self.loop_blocks: List[Tuple[int, str, List[Tuple[str, int]]]] = []
        # Frame blocks (non-loop item-name value pairs): (first_line, category_name, [(item_name, line_num), ...])
        self.frame_blocks: List[Tuple[int, str, List[Tuple[str, int]]]] = []
        
    def parse(self):
        """Parse the mmCIF file. Only parses the first data block."""
        with open(self.cif_path, 'r', encoding='utf-8') as f:
            self.lines = f.readlines()
        
        # Find the first data block and determine where to stop parsing
        first_data_block_line = None
        second_data_block_line = None
        
        for line_num, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if stripped.startswith('data_'):
                if first_data_block_line is None:
                    first_data_block_line = line_num
                else:
                    second_data_block_line = line_num
                    break
        
        # Determine parsing range:
        # - Start from first data block (or line 1 if no data block found, for backward compatibility)
        # - Stop at second data block (or end of file if no second data block)
        start_line = first_data_block_line if first_data_block_line is not None else 1
        max_line = len(self.lines) if second_data_block_line is None else second_data_block_line - 1
        
        current_loop_items = []
        in_loop = False
        is_real_loop = False  # True if loop started with 'loop_' directive, False if pseudo-loop from single item
        loop_start_line = 0
        partial_row_values = []  # Accumulate values for multi-line rows: [(value, line_num), ...]
        partial_row_line_nums = []  # Track line numbers for each value in partial_row_values
        expected_columns = 0
        self._in_multiline_string = False  # Track if we're inside a multi-line string
        self._multiline_content = ""  # Accumulate multi-line string content
        self._multiline_start_line = 0  # Track line where multi-line string started
        # Frame block (non-loop): [start_line, category, [(item_name, line_num), ...]] or None
        current_frame_block = None
        # Categories that have been closed (we left them via loop_ or different category) - re-appearance is duplicate category
        closed_frame_categories: Set[str] = set()
        
        for line_num, line in enumerate(self.lines, 1):
            # Skip lines before the first data block
            if line_num < start_line:
                continue
            # Stop parsing if we've reached the second data block
            if line_num > max_line:
                break
                
            stripped = line.strip()
            
            # Skip comments and empty lines
            if not stripped or stripped.startswith('#'):
                # If we're in a loop and hit a comment, it might end the loop
                # But also might be within a multi-line value, so we continue accumulating
                if in_loop and current_loop_items and partial_row_values:
                    # Comment might indicate end of loop, but let's be safe and continue
                    continue
                elif in_loop and current_loop_items:
                    # Empty line or comment - might be end of loop or continuation
                    # If we have partial values, continue accumulating
                    if partial_row_values:
                        continue
                continue
            
            # Check for loop_ directive
            if stripped == 'loop_':
                # Close current frame block (non-loop items) if any
                if current_frame_block is not None:
                    closed_frame_categories.add(current_frame_block[1])
                    self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
                    current_frame_block = None
                # Record the previous loop block (for duplicate category/item detection)
                if in_loop and is_real_loop and current_loop_items:
                    first_item_name = current_loop_items[0][0]
                    cat = first_item_name[1:].split('.')[0] if (first_item_name.startswith('_') and '.' in first_item_name) else ''
                    self.loop_blocks.append((loop_start_line, cat, list(current_loop_items)))
                # Finish any partial row before starting new loop
                if partial_row_values and current_loop_items:
                    self._assign_loop_row(current_loop_items, partial_row_values, partial_row_line_nums)
                in_loop = True
                is_real_loop = True  # This is a real loop directive
                current_loop_items = []
                partial_row_values = []
                partial_row_line_nums = []
                expected_columns = 0
                loop_start_line = line_num
                self._in_multiline_string = False
                self._multiline_content = ""
                self._multiline_start_line = 0
                continue
            
            # Check for item names (start with _)
            if stripped.startswith('_'):
                if '.' in stripped:
                    parts = stripped.split(None, 1)
                    item_name = parts[0]
                    value = parts[1] if len(parts) > 1 else None
                    
                    # Extract category name (part before the dot, without leading underscore)
                    if item_name.startswith('_') and '.' in item_name:
                        category = item_name[1:].split('.')[0]
                        self.categories.add(category)
                    
                    if in_loop:
                        # In a loop: item with no value is a loop header; item with value ends the loop
                        if value is None:
                            current_loop_items.append((item_name, line_num))
                            expected_columns = len(current_loop_items)
                        else:
                            # Item name with value - this ends the loop, finish any partial row
                            if partial_row_values and current_loop_items:
                                self._assign_loop_row(current_loop_items, partial_row_values, partial_row_line_nums)
                            # Record this loop block before leaving loop mode (for duplicate category/item detection)
                            if is_real_loop and current_loop_items:
                                first_item_name = current_loop_items[0][0]
                                cat = first_item_name[1:].split('.')[0] if (first_item_name.startswith('_') and '.' in first_item_name) else ''
                                self.loop_blocks.append((loop_start_line, cat, list(current_loop_items)))
                            in_loop = False
                            is_real_loop = False
                            current_loop_items = []
                            partial_row_values = []
                            partial_row_line_nums = []
                            expected_columns = 0
                            # Process this as a regular item
                            if item_name not in self.items:
                                self.items[item_name] = []
                            # Strip quotes and whitespace from value
                            if value is not None:
                                value = value.strip("'\" ")
                            self.items[item_name].append(ItemValue(line_num, value, 0, 1))  # global_column_index = 0, local_column_index = 1 for non-loop items (item name is at 0, value is at 1)
                            # Record frame block (for duplicate category/item detection)
                            if category:
                                if category in closed_frame_categories:
                                    # Re-appearing category (e.g. struct again after a loop) = new block, duplicate category
                                    if current_frame_block is not None:
                                        self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
                                    current_frame_block = [line_num, category, [(item_name, line_num)]]
                                elif current_frame_block is not None and current_frame_block[1] == category:
                                    # Same category: if this item already in block, we're re-starting category (duplicate)
                                    if any(x[0] == item_name for x in current_frame_block[2]):
                                        closed_frame_categories.add(category)
                                        self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
                                        current_frame_block = [line_num, category, [(item_name, line_num)]]
                                    else:
                                        current_frame_block[2].append((item_name, line_num))
                                elif current_frame_block is not None and current_frame_block[1] != category:
                                    closed_frame_categories.add(current_frame_block[1])
                                    self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
                                    current_frame_block = [line_num, category, [(item_name, line_num)]]
                                elif current_frame_block is None:
                                    current_frame_block = [line_num, category, [(item_name, line_num)]]
                                else:
                                    current_frame_block[2].append((item_name, line_num))
                    else:
                        # Not in a loop - regular item
                        if item_name not in self.items:
                            self.items[item_name] = []
                        if value is not None:
                            # Strip quotes and whitespace from value
                            value = value.strip("'\" ")
                            self.items[item_name].append(ItemValue(line_num, value, 0, 1))  # global_column_index = 0, local_column_index = 1 for non-loop items (item name is at 0, value is at 1)
                            # Record frame block (for duplicate category/item detection)
                            if category:
                                if category in closed_frame_categories:
                                    if current_frame_block is not None:
                                        self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
                                    current_frame_block = [line_num, category, [(item_name, line_num)]]
                                elif current_frame_block is not None and current_frame_block[1] == category:
                                    if any(x[0] == item_name for x in current_frame_block[2]):
                                        closed_frame_categories.add(category)
                                        self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
                                        current_frame_block = [line_num, category, [(item_name, line_num)]]
                                    else:
                                        current_frame_block[2].append((item_name, line_num))
                                elif current_frame_block is not None and current_frame_block[1] != category:
                                    closed_frame_categories.add(current_frame_block[1])
                                    self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
                                    current_frame_block = [line_num, category, [(item_name, line_num)]]
                                elif current_frame_block is None:
                                    current_frame_block = [line_num, category, [(item_name, line_num)]]
                                else:
                                    current_frame_block[2].append((item_name, line_num))
                        else:
                            # Item name without value - start a new pseudo-loop (for multi-line string handling)
                            current_loop_items = [(item_name, line_num)]
                            in_loop = True
                            is_real_loop = False  # This is a pseudo-loop, not a real loop_ directive
                            loop_start_line = line_num
                            expected_columns = 1
                            partial_row_values = []
                            partial_row_line_nums = []
            
            # Parse loop data
            elif in_loop and current_loop_items:
                # Check if this line starts a multi-line string (starts with ;)
                if stripped.startswith(';'):
                    # Check if we're already in a multi-line string
                    if self._in_multiline_string:
                        # Check if this is the closing ; (must be exactly ;)
                        if stripped == ';':
                            # End of multi-line string - add accumulated content as a value
                            partial_row_values.append(self._multiline_content)
                            partial_row_line_nums.append(self._multiline_start_line)
                            self._multiline_content = ""
                            self._in_multiline_string = False
                            self._multiline_start_line = 0
                            
                            # After closing multi-line string, check if row is complete
                            # Note: There might be more values on the next line(s)
                            if len(partial_row_values) >= expected_columns:
                                # Assign complete row
                                self._assign_loop_row(current_loop_items, partial_row_values[:expected_columns], partial_row_line_nums[:expected_columns])
                                # Keep any extra values for next row
                                partial_row_values = partial_row_values[expected_columns:]
                                partial_row_line_nums = partial_row_line_nums[expected_columns:]
                                
                                # If this was a single-item pseudo-loop (not a real loop_) and row is complete,
                                # reset loop state to prevent next item from being incorrectly added to this loop
                                if not is_real_loop and expected_columns == 1 and len(current_loop_items) == 1 and len(partial_row_values) == 0:
                                    in_loop = False
                                    is_real_loop = False
                                    current_loop_items = []
                                    expected_columns = 0
                                
                                # If this was a single-item pseudo-loop (not a real loop_), 
                                # and we've completed the row, reset loop state
                                # This fixes the bug where consecutive single-value items with
                                # multi-line strings get incorrectly grouped together
                                if not is_real_loop and expected_columns == 1 and len(partial_row_values) == 0:
                                    in_loop = False
                                    is_real_loop = False
                                    current_loop_items = []
                                    expected_columns = 0
                        else:
                            # Continue accumulating multi-line content (line starts with ; but has more)
                            if self._multiline_content:
                                self._multiline_content += "\n"
                            # Don't include the leading ; in the content
                            self._multiline_content += stripped[1:] if len(stripped) > 1 else ""
                    else:
                        # Start of multi-line string
                        self._in_multiline_string = True
                        self._multiline_content = ""
                        self._multiline_start_line = line_num
                        # Check if there's content after the ; on the same line
                        if len(stripped) > 1:
                            # There's content on the same line after ;
                            remaining = stripped[1:].strip()
                            if remaining:
                                self._multiline_content = remaining
                elif self._in_multiline_string:
                    # We're inside a multi-line string - accumulate content
                    if self._multiline_content:
                        self._multiline_content += "\n"
                    self._multiline_content += stripped
                else:
                    # Regular data line in loop - parse values and accumulate
                    # This might be a continuation after a multi-line string closed
                    values = self._parse_loop_line(stripped)
                    partial_row_values.extend(values)
                    # All values from this line share the same line number
                    partial_row_line_nums.extend([line_num] * len(values))
                    
                    # Check if we have a complete row (all columns filled)
                    if len(partial_row_values) >= expected_columns:
                        # Assign complete row
                        self._assign_loop_row(current_loop_items, partial_row_values[:expected_columns], partial_row_line_nums[:expected_columns])
                        # Keep any extra values for next row
                        partial_row_values = partial_row_values[expected_columns:]
                        partial_row_line_nums = partial_row_line_nums[expected_columns:]
        
        # Finish any remaining partial row
        if in_loop and current_loop_items and partial_row_values:
            self._assign_loop_row(current_loop_items, partial_row_values, partial_row_line_nums)
        
        # Record the last loop block (for duplicate category/item detection)
        if in_loop and is_real_loop and current_loop_items:
            first_item_name = current_loop_items[0][0]
            cat = first_item_name[1:].split('.')[0] if (first_item_name.startswith('_') and '.' in first_item_name) else ''
            self.loop_blocks.append((loop_start_line, cat, list(current_loop_items)))
        
        # Close final frame block if any
        if current_frame_block is not None:
            self.frame_blocks.append((current_frame_block[0], current_frame_block[1], list(current_frame_block[2])))
        
        # Clean up multi-line string state
        if hasattr(self, '_in_multiline_string'):
            delattr(self, '_in_multiline_string')
        if hasattr(self, '_multiline_content'):
            delattr(self, '_multiline_content')
        
        return self
    
    def _assign_loop_row(self, loop_items: List[Tuple[str, int]], values: List[str], line_nums: List[int]):
        """Assign values from a complete loop row to their respective items.
        
        Args:
            loop_items: List of (item_name, header_line_num) tuples
            values: List of values for this row
            line_nums: List of line numbers, one per value (where each value appears)
        """
        # Calculate local column indices: count how many values appear on each line
        line_value_counts = {}  # Map line_num -> count of values on that line (so far)
        local_column_indices = []
        
        for i, line_num in enumerate(line_nums):
            if line_num not in line_value_counts:
                line_value_counts[line_num] = 0
            local_column_indices.append(line_value_counts[line_num])
            line_value_counts[line_num] += 1
        
        for i, (item_name, _) in enumerate(loop_items):
            if i < len(values):
                # Extract category name
                if item_name.startswith('_') and '.' in item_name:
                    category = item_name[1:].split('.')[0]
                    self.categories.add(category)
                if item_name not in self.items:
                    self.items[item_name] = []
                # Use the line number where this specific value appears
                value_line_num = line_nums[i] if i < len(line_nums) else line_nums[-1] if line_nums else 1
                # Global column index is the position in the row (0-based)
                global_column_index = i
                # Local column index is the position on this specific line (0-based)
                local_column_index = local_column_indices[i] if i < len(local_column_indices) else 0
                self.items[item_name].append(ItemValue(value_line_num, values[i], global_column_index, local_column_index))
    
    def _parse_loop_line(self, line: str) -> List[str]:
        """Parse a line of loop data, handling quoted strings."""
        values = []
        current = ""
        in_quotes = False
        quote_char = None
        
        i = 0
        while i < len(line):
            char = line[i]
            
            if not in_quotes:
                if char in ["'", '"']:
                    in_quotes = True
                    quote_char = char
                    # Don't include the opening quote
                elif char == ' ' or char == '\t':
                    if current.strip():
                        values.append(current.strip())
                        current = ""
                else:
                    current += char
            else:
                if char == quote_char and (i == 0 or line[i-1] != '\\'):
                    # Closing quote - don't include it
                    in_quotes = False
                    quote_char = None
                else:
                    current += char
            
            i += 1
        
        if current.strip():
            values.append(current.strip())
        
        return values
    
    def get_category_rows(self, category: str) -> List[Dict[str, ItemValue]]:
        """
        Get all rows in a category as dictionaries.
        Reconstructs rows by matching values at the same index across items.

        Returns: List of dicts, each dict maps item_name -> ItemValue(line_num, value, global_col, local_col)
        """
        # Get all items in this category
        category_items = {name: values for name, values in self.items.items() 
                         if name.startswith('_') and name[1:].split('.')[0] == category}
        
        if not category_items:
            return []
        
        # Find the maximum number of rows (max length of any item's value list)
        max_rows = max(len(values) for values in category_items.values()) if category_items else 0
        
        rows = []
        for row_idx in range(max_rows):
            row = {}
            for item_name, values_list in category_items.items():
                if row_idx < len(values_list):
                    row[item_name] = values_list[row_idx]
            if row:  # Only add non-empty rows
                rows.append(row)
        
        return rows
