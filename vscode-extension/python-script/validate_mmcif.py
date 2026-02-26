#!/usr/bin/env python3
"""
mmCIF Dictionary Validator

Validates mmCIF files against a dictionary file (mmcif_pdbx_v5_next.dic).

Author: Deborah Harrus
Organization: Protein Data Bank in Europe (PDBe), EMBL-EBI
"""

import re
import sys
import json
import argparse
import urllib.request
import tempfile
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ValidationError:
    """Represents a validation error."""
    line: int
    item: str
    message: str
    severity: str = "error"  # error, warning
    column: Optional[int] = None  # Column index (0-based) within the line, for loop data
    start_char: Optional[int] = None  # Character start position within the line
    end_char: Optional[int] = None  # Character end position within the line


class DictionaryParser:
    """Parses mmCIF dictionary files."""
    
    def __init__(self, dict_path: Path):
        self.dict_path = dict_path
        self.items: Dict[str, Dict] = {}
        self.categories: Dict[str, Dict] = {}
        self.mandatory_items: Set[str] = set()
        self.parent_child_relationships: List[Dict] = []  # List of {child_cat, parent_cat, child_item, parent_item}
        self.type_regex_patterns: Dict[str, str] = {}  # Map type code to regex pattern
        self.type_regex_patterns: Dict[str, str] = {}  # Map type code to regex pattern
        
    def parse(self):
        """Parse the dictionary file."""
        with open(self.dict_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse save blocks
        save_pattern = r'save_([^\n]+)\n(.*?)(?=save_|$)'
        matches = re.finditer(save_pattern, content, re.DOTALL)
        
        current_item = None
        current_category = None
        
        for match in matches:
            block_name = match.group(1).strip()
            block_content = match.group(2)
            
            # Parse item definitions
            if block_name.startswith('_') and '.' in block_name:
                item_name = block_name
                item_info = self._parse_item_block(block_content)
                if item_info:
                    self.items[item_name] = item_info
                    if item_info.get('mandatory') == 'yes':
                        self.mandatory_items.add(item_name)
            
            # Parse category definitions
            elif not block_name.startswith('_'):
                category_info = self._parse_category_block(block_content, block_name)
                if category_info:
                    self.categories[block_name] = category_info
        
        # Parse parent/child relationships from _pdbx_item_linked_group_list
        self._parse_parent_child_relationships(content)
        
        # Parse type regex patterns from _item_type_list
        self._parse_type_regex_patterns(content)
        
        return self
    
    def _parse_item_block(self, content: str) -> Optional[Dict]:
        """Parse an item definition block."""
        item_info = {}
        
        # Extract item name
        name_match = re.search(r'_item\.name\s+([^\n]+)', content)
        if not name_match:
            return None
        
        item_name = name_match.group(1).strip().strip("'\"")
        item_info['name'] = item_name
        
        # Extract mandatory code
        mandatory_match = re.search(r'_item\.mandatory_code\s+(\w+)', content)
        if mandatory_match:
            item_info['mandatory'] = mandatory_match.group(1).strip()
        
        # Extract category ID
        category_match = re.search(r'_item\.category_id\s+(\w+)', content)
        if category_match:
            item_info['category'] = category_match.group(1).strip()
        
        # Extract data type
        # Match type codes that can contain hyphens, colons, and other characters
        # Examples: yyyy-mm-dd, yyyy-mm-dd:hh:mm, float-range, etc.
        type_match = re.search(r'_item_type\.code\s+([^\s\n#]+)', content)
        if type_match:
            item_info['type'] = type_match.group(1).strip()
        
        # Check if this item is linked/referenced (enumeration might not be exhaustive)
        linked_match = re.search(r'_item_linked\.(?:child_name|parent_name)', content)
        if linked_match:
            item_info['is_linked'] = True
        
        # Extract enumerations
        # Look for loop_ followed by enumeration headers, then data lines
        # Pattern must handle multiple cases:
        # 1. loop_ with _item_enumeration.name, _item_enumeration.value, _item_enumeration.detail
        # 2. loop_ with _item_enumeration.value and _item_enumeration.detail (no name)
        # 3. loop_ with only _item_enumeration.value
        # The format can be:
        #   loop_
        #   _item_enumeration.name (optional)
        #   _item_enumeration.value
        #   _item_enumeration.detail (optional)
        # Match loop_ followed by any lines starting with _item_enumeration, then capture data lines
        # Try pattern where loop_ is on one line and enumeration headers are on following lines
        enum_pattern = r'loop_\s*\n((?:\s*_item_enumeration\.(?:name|value|detail)\s*\n)+)(.*?)(?=\s*#|save_|$)'
        enum_match = re.search(enum_pattern, content, re.DOTALL)
        # If that doesn't match, try pattern where headers are on same line as loop_
        if not enum_match:
            enum_pattern = r'loop_\s+((?:_item_enumeration\.(?:name|value|detail)\s+)+)\s*\n(.*?)(?=\s*#|save_|$)'
            enum_match = re.search(enum_pattern, content, re.DOTALL)
        if enum_match:
            header_lines = enum_match.group(1).strip()
            enum_data = enum_match.group(2).strip()
            item_info['enumerations'] = []
            
            # Determine which column contains the value by checking the header
            # Count how many _item_enumeration columns there are and find value position
            header_columns = re.findall(r'_item_enumeration\.(name|value|detail)', header_lines)
            value_column_index = None
            for idx, col_type in enumerate(header_columns):
                if col_type == 'value':
                    value_column_index = idx
                    break
            
            # Fallback: if we couldn't find value in header, assume it's first column (index 0)
            if value_column_index is None:
                value_column_index = 0
            
            # Parse each line of enumeration data
            for line in enum_data.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    # Parse the line - handle quoted and unquoted values
                    values = self._parse_enumeration_line(line)
                    if values and len(values) > value_column_index:
                        item_info['enumerations'].append(values[value_column_index])
        
        # Extract range constraints
        # Parse both _item_range (strictly Allowed Boundary Conditions) and 
        # _pdbx_item_range (Advisory Boundary Conditions) separately
        # Ranges can be single values or loop structures with multiple ranges
        
        # Parse _item_range (strictly Allowed Boundary Conditions)
        # Dictionary can have either order: maximum minimum or minimum maximum
        item_range_loop_max_min = re.search(r'loop_\s*_item_range\.maximum\s+_item_range\.minimum\s*\n(.*?)(?=\s*#|save_|$)', content, re.DOTALL)
        item_range_loop_min_max = re.search(r'loop_\s*_item_range\.minimum\s+_item_range\.maximum\s*\n(.*?)(?=\s*#|save_|$)', content, re.DOTALL)
        
        if item_range_loop_max_min:
            # Parse loop structure for _item_range (maximum minimum order)
            range_data = item_range_loop_max_min.group(1).strip()
            ranges = []
            for line in range_data.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    values = line.split()
                    if len(values) >= 2:
                        max_val = values[0].strip()
                        min_val = values[1].strip()
                        # Keep all ranges - they will be combined to determine overall bounds
                        # Ranges with min==max mean "exactly this value" and are combined with other ranges
                        if max_val != '.' or min_val != '.':
                            ranges.append({'min': min_val, 'max': max_val})
            if ranges:
                item_info['allowed_ranges'] = ranges
        elif item_range_loop_min_max:
            # Parse loop structure for _item_range (minimum maximum order)
            range_data = item_range_loop_min_max.group(1).strip()
            ranges = []
            for line in range_data.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    values = line.split()
                    if len(values) >= 2:
                        min_val = values[0].strip()
                        max_val = values[1].strip()
                        # Keep all ranges - they will be combined to determine overall bounds
                        # Ranges with min==max mean "exactly this value" and are combined with other ranges
                        if max_val != '.' or min_val != '.':
                            ranges.append({'min': min_val, 'max': max_val})
            if ranges:
                item_info['allowed_ranges'] = ranges
        else:
            # Check for single _item_range values
            item_min_match = re.search(r'_item_range\.minimum\s+([^\s\n#]+)', content)
            item_max_match = re.search(r'_item_range\.maximum\s+([^\s\n#]+)', content)
            if item_min_match or item_max_match:
                if item_min_match:
                    min_val = item_min_match.group(1).strip()
                    if min_val != '.':
                        item_info['allowed_range_min'] = min_val
                if item_max_match:
                    max_val = item_max_match.group(1).strip()
                    if max_val != '.':
                        item_info['allowed_range_max'] = max_val
        
        # Parse _pdbx_item_range (Advisory Boundary Conditions)
        # Pattern: loop_ with name, minimum, maximum (in that order)
        pdbx_range_loop = re.search(r'loop_\s*_pdbx_item_range\.name\s+_pdbx_item_range\.minimum\s+_pdbx_item_range\.maximum\s*\n(.*?)(?=\s*#|save_|$)', content, re.DOTALL)
        if pdbx_range_loop:
            # Parse loop structure for _pdbx_item_range
            # Format: name min max (skip name, use min and max)
            range_data = pdbx_range_loop.group(1).strip()
            ranges = []
            for line in range_data.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    values = line.split()
                    if len(values) >= 3:
                        # Skip name (first value), use min (second) and max (third)
                        min_val = values[1].strip()
                        max_val = values[2].strip()
                        if max_val != '.' or min_val != '.':
                            ranges.append({'min': min_val, 'max': max_val})
                    elif len(values) >= 2:
                        # Fallback: if only 2 values, assume min and max (no name)
                        min_val = values[0].strip()
                        max_val = values[1].strip()
                        if max_val != '.' or min_val != '.':
                            ranges.append({'min': min_val, 'max': max_val})
            if ranges:
                item_info['advisory_ranges'] = ranges
        else:
            # Try pattern without name field (just minimum and maximum)
            pdbx_range_loop_no_name = re.search(r'loop_\s*_pdbx_item_range\.(?:maximum\s+_pdbx_item_range\.minimum|minimum\s+_pdbx_item_range\.maximum)\s*\n(.*?)(?=\s*#|save_|$)', content, re.DOTALL)
            if pdbx_range_loop_no_name:
                # Parse loop structure for _pdbx_item_range without name
                range_data = pdbx_range_loop_no_name.group(1).strip()
                ranges = []
                for line in range_data.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):
                        values = line.split()
                        if len(values) >= 2:
                            # Check which order: max min or min max
                            # Try to determine by checking if first is larger (likely max) or smaller (likely min)
                            # For simplicity, assume max min order (same as _item_range)
                            max_val = values[0].strip()
                            min_val = values[1].strip()
                            if max_val != '.' or min_val != '.':
                                ranges.append({'min': min_val, 'max': max_val})
                if ranges:
                    item_info['advisory_ranges'] = ranges
            else:
                # Check for single _pdbx_item_range values (without loop)
                pdbx_min_match = re.search(r'_pdbx_item_range\.minimum\s+([^\s\n#]+)', content)
                pdbx_max_match = re.search(r'_pdbx_item_range\.maximum\s+([^\s\n#]+)', content)
                if pdbx_min_match or pdbx_max_match:
                    if pdbx_min_match:
                        min_val = pdbx_min_match.group(1).strip()
                        if min_val != '.':
                            item_info['advisory_range_min'] = min_val
                    if pdbx_max_match:
                        max_val = pdbx_max_match.group(1).strip()
                        if max_val != '.':
                            item_info['advisory_range_max'] = max_val
        
        return item_info
    
    def _parse_enumeration_line(self, line: str) -> List[str]:
        """Parse a line of enumeration data, handling quoted values."""
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
                    # Closing quote - don't include it, finish this value
                    in_quotes = False
                    quote_char = None
                    if current.strip():
                        values.append(current.strip())
                        current = ""
                else:
                    current += char
            
            i += 1
        
        if current.strip():
            values.append(current.strip())
        
        return values
    
    def _parse_category_block(self, content: str, category_name: str) -> Optional[Dict]:
        """Parse a category definition block."""
        category_info = {'id': category_name}
        
        # Extract mandatory code
        mandatory_match = re.search(r'_category\.mandatory_code\s+(\w+)', content)
        if mandatory_match:
            category_info['mandatory'] = mandatory_match.group(1).strip()
        
        # Extract category keys
        key_pattern = r'_category_key\.name\s+([^\n]+)'
        key_matches = re.finditer(key_pattern, content)
        category_info['keys'] = []
        for key_match in key_matches:
            key_name = key_match.group(1).strip().strip("'\"")
            category_info['keys'].append(key_name)
        
        return category_info
    
    def _parse_parent_child_relationships(self, content: str):
        """Parse parent/child category relationships from _pdbx_item_linked_group_list."""
        # Find the loop_ block for _pdbx_item_linked_group_list
        # Pattern: loop_ followed by headers, then data rows
        pattern = r'loop_\s*_pdbx_item_linked_group_list\.child_category_id\s*_pdbx_item_linked_group_list\.link_group_id\s*_pdbx_item_linked_group_list\.child_name\s*_pdbx_item_linked_group_list\.parent_name\s*_pdbx_item_linked_group_list\.parent_category_id\s*\n(.*?)(?=\n\s*#|save_|$)'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            data_section = match.group(1).strip()
            # Parse each line - format: child_cat link_group_id "child_item" "parent_item" parent_cat
            for line in data_section.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Parse the line - handle quoted strings properly
                values = self._parse_enumeration_line(line)  # Reuse existing parser for quoted values
                if len(values) >= 5:
                    child_cat = values[0].strip()
                    link_group_id = values[1].strip()
                    child_item = values[2].strip().strip("'\"")
                    parent_item = values[3].strip().strip("'\"")
                    parent_cat = values[4].strip()
                    
                    self.parent_child_relationships.append({
                        'child_category': child_cat,
                        'parent_category': parent_cat,
                        'child_item': child_item,
                        'parent_item': parent_item,
                        'link_group_id': link_group_id
                    })
    
    def _parse_type_regex_patterns(self, content: str):
        """Parse type code regex patterns from _item_type_list."""
        # Find the loop_ block for _item_type_list
        # Pattern: loop_ followed by headers, then data rows
        pattern = r'loop_\s*_item_type_list\.code\s*_item_type_list\.primitive_code\s*_item_type_list\.construct\s*_item_type_list\.detail\s*\n(.*?)(?=\n\s*#|save_|$)'
        match = re.search(pattern, content, re.DOTALL)
        
        if not match:
            return
        
        data_section = match.group(1).strip()
        lines = data_section.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith('#'):
                i += 1
                continue
            
            # Parse: type_code primitive_code [construct]
            parts = line.split(None, 2)  # Split into max 3 parts
            if len(parts) < 2:
                i += 1
                continue
            
            type_code = parts[0].strip()
            primitive_code = parts[1].strip()
            regex_pattern = None
            
            # Case 1: Construct is on the same line
            if len(parts) > 2:
                construct_part = parts[2].strip()
                
                # Check if it's a quoted string
                if construct_part.startswith('"'):
                    # Extract the first quoted string (the pattern)
                    # There might be a second quoted string (the detail) after it
                    quote_match = re.search(r'^"(.*?)"', construct_part)
                    if quote_match:
                        regex_pattern = quote_match.group(1)
                    else:
                        # Quoted string might span lines - collect until closing quote
                        pattern_parts = [construct_part]
                        i += 1
                        while i < len(lines):
                            next_line = lines[i].strip()
                            pattern_parts.append(next_line)
                            if '"' in next_line:
                                # Found closing quote
                                full_pattern = ' '.join(pattern_parts)
                                # Extract the first quoted part
                                quote_match = re.search(r'"(.*?)"', full_pattern)
                                if quote_match:
                                    regex_pattern = quote_match.group(1)
                                break
                            i += 1
                # Check if it's an unquoted pattern (not starting with ;)
                elif not construct_part.startswith(';'):
                    # For unquoted patterns, take everything up to the first quote or end of line
                    # (detail might be quoted after the pattern)
                    if '"' in construct_part:
                        # Pattern ends before the quote (which is the detail)
                        regex_pattern = construct_part.split('"')[0].strip()
                    else:
                        regex_pattern = construct_part
            
            # Case 2: Construct starts on next line with ;
            if regex_pattern is None:
                i += 1
                if i < len(lines):
                    next_line = lines[i].strip()
                    if next_line.startswith(';'):
                        # Multi-line pattern between ; and ;
                        pattern_lines = []
                        i += 1  # Skip opening ;
                        
                        # Collect lines until we find the closing ;
                        while i < len(lines):
                            line_content = lines[i].strip()
                            if line_content.startswith(';'):
                                # Found closing ; - end of pattern
                                break
                            pattern_lines.append(line_content)
                            i += 1
                        
                        # Join pattern lines and clean up
                        regex_pattern = ' '.join(pattern_lines).strip()
            
            # Store the pattern if we found one
            if regex_pattern:
                self.type_regex_patterns[type_code] = regex_pattern
            
            # Skip detail lines (everything after the closing ; until next type_code line)
            # Find the next line that looks like a type_code definition
            # A type_code line has: type_code primitive_code [construct]
            # Where primitive_code is one of: char, numb, uchar
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line or next_line.startswith('#'):
                    i += 1
                    continue
                # Check if this looks like a new type_code line
                # It should have at least 2 words, and the second should be a primitive_code
                parts_check = next_line.split(None, 2)
                if len(parts_check) >= 2:
                    potential_primitive = parts_check[1].strip()
                    if potential_primitive in ['char', 'numb', 'uchar']:
                        # This is the next type_code line
                        break
                i += 1


class MmCIFParser:
    """Parses mmCIF files."""
    
    def __init__(self, cif_path: Path):
        self.cif_path = cif_path
        self.items: Dict[str, List[Tuple[int, str, int, int]]] = {}  # item_name -> [(line_num, value, global_column_index, local_column_index), ...]
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
                            self.items[item_name].append((line_num, value, 0, 1))  # global_column_index = 0, local_column_index = 1 for non-loop items (item name is at 0, value is at 1)
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
                            self.items[item_name].append((line_num, value, 0, 1))  # global_column_index = 0, local_column_index = 1 for non-loop items (item name is at 0, value is at 1)
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
                self.items[item_name].append((value_line_num, values[i], global_column_index, local_column_index))
    
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
    
    def get_category_rows(self, category: str) -> List[Dict[str, Tuple[int, str, int, int]]]:
        """
        Get all rows in a category as dictionaries.
        Reconstructs rows by matching values at the same index across items.
        
        Returns: List of dicts, each dict maps item_name -> (line_num, value, global_col, local_col)
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


class MmCIFValidator:
    """Validates mmCIF files against a dictionary."""
    
    def __init__(self, dictionary: DictionaryParser, mmcif: MmCIFParser):
        self.dictionary = dictionary
        self.mmcif = mmcif
        self.errors: List[ValidationError] = []
    
    def validate(self) -> List[ValidationError]:
        """Perform validation and return list of errors."""
        self.errors = []
        
        # Check for duplicate categories (same category in more than one block: loop or frame)
        all_blocks = list(getattr(self.mmcif, 'loop_blocks', [])) + list(getattr(self.mmcif, 'frame_blocks', []))
        seen_categories: Dict[str, int] = {}
        reported_duplicate_categories: Set[str] = set()
        for block_start_line, category, block_items in all_blocks:
            if not category:
                continue
            if category in seen_categories:
                # Report duplicate category only once per category (at first duplicate block)
                if category not in reported_duplicate_categories:
                    reported_duplicate_categories.add(category)
                    self.errors.append(ValidationError(
                        line=block_start_line,
                        item=f"_{category}.",
                        message=f"Duplicate category '{category}' (first occurrence at line {seen_categories[category]})",
                        severity="error"
                    ))
            else:
                seen_categories[category] = block_start_line
        
        # Check for duplicate items within a block and across blocks of same category
        seen_items_by_category: Dict[str, Dict[str, int]] = {}  # category -> {item_name: first_line}
        for block_start_line, category, block_items in all_blocks:
            seen_items_in_block: Dict[str, int] = {}
            for item_name, item_line in block_items:
                # Duplicate within same block
                if item_name in seen_items_in_block:
                    self.errors.append(ValidationError(
                        line=item_line,
                        item=item_name,
                        message=f"Duplicate item '{item_name}' (first occurrence at line {seen_items_in_block[item_name]})",
                        severity="error"
                    ))
                else:
                    seen_items_in_block[item_name] = item_line
                    # Duplicate in same category in a previous block
                    if category and category in seen_items_by_category and item_name in seen_items_by_category[category]:
                        self.errors.append(ValidationError(
                            line=item_line,
                            item=item_name,
                            message=f"Duplicate item '{item_name}' (first occurrence at line {seen_items_by_category[category][item_name]})",
                            severity="error"
                        ))
                if category:
                    if category not in seen_items_by_category:
                        seen_items_by_category[category] = {}
                    if item_name not in seen_items_by_category[category]:
                        seen_items_by_category[category][item_name] = item_line
        
        # Check for undefined items
        for item_name in self.mmcif.items:
            if item_name not in self.dictionary.items:
                # Allow items that start with underscore (might be valid but not in dict)
                # Only warn if it's clearly not a standard item
                if not item_name.startswith('_'):
                    line_num = self.mmcif.items[item_name][0][0] if self.mmcif.items[item_name] else 1
                    self.errors.append(ValidationError(
                        line=line_num,
                        item=item_name,
                        message=f"Item '{item_name}' is not defined in the dictionary",
                        severity="warning"
                    ))
        
        # Check for missing mandatory items (only for categories that are present)
        for mandatory_item in self.dictionary.mandatory_items:
            if mandatory_item not in self.mmcif.items:
                # Extract category from item name (format: _category.item_name)
                if mandatory_item.startswith('_') and '.' in mandatory_item:
                    category = mandatory_item[1:].split('.')[0]
                    # Only check if the category is present in the file
                    if category in self.mmcif.categories:
                        # Find approximate line number (search for category)
                        line_num = self._find_category_line(category)
                        self.errors.append(ValidationError(
                            line=line_num if line_num > 0 else 1,
                            item=mandatory_item,
                            message=f"Mandatory item '{mandatory_item}' is missing",
                            severity="error"
                        ))
        
        # Validate item values against enumerations
        # Skip enumeration validation for linked items (they reference other items, enumerations are examples)
        # Also skip for atom_id, comp_id, and similar items that can have many valid values
        skip_enum_items = ['atom_id', 'comp_id', 'asym_id', 'seq_id', 'label_', 'auth_']
        
        for item_name, values in self.mmcif.items.items():
            if item_name in self.dictionary.items:
                item_def = self.dictionary.items[item_name]
                
                # Skip enumeration validation for linked items or items that reference IDs
                should_skip = False
                if item_def.get('is_linked', False):
                    should_skip = True
                else:
                    # Check if item name suggests it's an ID/reference field
                    for skip_pattern in skip_enum_items:
                        if skip_pattern in item_name.lower():
                            should_skip = True
                            break
                
                if 'enumerations' in item_def and not should_skip:
                    allowed_values = set(item_def['enumerations'])
                    for line_num, value, global_column_index, local_column_index in values:
                        # Handle '?' and '.' as valid (missing/unknown values)
                        if value not in ['?', '.'] and value not in allowed_values:
                            # Enumeration validation reports as error since values must match the controlled vocabulary
                            # Sort enumeration values alphabetically for consistent display
                            sorted_values = sorted(allowed_values)
                            self.errors.append(self._create_validation_error(
                                line_num=line_num,
                                item_name=item_name,
                                message=f"Value '{value}' is not in enumeration examples: {sorted_values}",
                                severity="error",
                                global_column_index=global_column_index,
                                local_column_index=local_column_index,
                                value=value
                            ))
                
                # Validate data types
                if 'type' in item_def:
                    item_type = item_def['type']
                    for line_num, value, global_column_index, local_column_index in values:
                        # Handle '?' and '.' as valid (missing/unknown values)
                        if value not in ['?', '.']:
                            if not self._validate_type(value, item_type):
                                self.errors.append(self._create_validation_error(
                                    line_num=line_num,
                                    item_name=item_name,
                                    message=f"Value '{value}' does not match expected type '{item_type}'",
                                    severity="error",
                                    global_column_index=global_column_index,
                                    local_column_index=local_column_index,
                                    value=value
                                ))
                
                # Validate range constraints
                # First check _item_range (strictly Allowed Boundary Conditions) - these are errors
                if 'allowed_ranges' in item_def:
                    # Multiple ranges (from loop structure) - value must match at least one
                    for line_num, value, global_column_index, local_column_index in values:
                        if value not in ['?', '.']:
                            range_error = self._validate_ranges(value, item_def['allowed_ranges'], item_def.get('type'))
                            if range_error:
                                self.errors.append(self._create_validation_error(
                                    line_num=line_num,
                                    item_name=item_name,
                                    message=range_error,
                                    severity="error",
                                global_column_index=global_column_index,
                                local_column_index=local_column_index,
                                value=value
                                ))
                elif 'allowed_range_min' in item_def or 'allowed_range_max' in item_def:
                    # Single range (from non-loop structure)
                    for line_num, value, global_column_index, local_column_index in values:
                        # Handle '?' and '.' as valid (missing/unknown values)
                        if value not in ['?', '.']:
                            range_error = self._validate_range(value, item_def.get('allowed_range_min'), item_def.get('allowed_range_max'), item_def.get('type'))
                            if range_error:
                                self.errors.append(self._create_validation_error(
                                    line_num=line_num,
                                    item_name=item_name,
                                    message=range_error,
                                    severity="error",
                                global_column_index=global_column_index,
                                local_column_index=local_column_index,
                                value=value
                                ))
                
                # Then check _pdbx_item_range (Advisory Boundary Conditions) - these are warnings
                if 'advisory_ranges' in item_def:
                    # Multiple ranges (from loop structure) - value must match at least one
                    for line_num, value, global_column_index, local_column_index in values:
                        if value not in ['?', '.']:
                            range_error = self._validate_ranges(value, item_def['advisory_ranges'], item_def.get('type'))
                            if range_error:
                                # Check if value is also outside allowed range
                                is_outside_allowed = False
                                if 'allowed_ranges' in item_def:
                                    allowed_error = self._validate_ranges(value, item_def['allowed_ranges'], item_def.get('type'))
                                    is_outside_allowed = allowed_error is not None
                                elif 'allowed_range_min' in item_def or 'allowed_range_max' in item_def:
                                    allowed_error = self._validate_range(value, item_def.get('allowed_range_min'), item_def.get('allowed_range_max'), item_def.get('type'))
                                    is_outside_allowed = allowed_error is not None
                                
                                # Adjust message wording: use "advised" if within allowed range, "allowed" if outside
                                if is_outside_allowed:
                                    # Value is outside allowed range - keep "allowed" wording
                                    message = f"Out of advisory range: {range_error}"
                                else:
                                    # Value is within allowed range but outside advisory - use "advised" wording
                                    message = f"Out of advisory range: {range_error.replace('allowed', 'advised')}"
                                
                                self.errors.append(self._create_validation_error(
                                    line_num=line_num,
                                    item_name=item_name,
                                    message=message,
                                    severity="warning",
                                global_column_index=global_column_index,
                                local_column_index=local_column_index,
                                value=value
                                ))
                elif 'advisory_range_min' in item_def or 'advisory_range_max' in item_def:
                    # Single range (from non-loop structure)
                    for line_num, value, global_column_index, local_column_index in values:
                        # Handle '?' and '.' as valid (missing/unknown values)
                        if value not in ['?', '.']:
                            range_error = self._validate_range(value, item_def.get('advisory_range_min'), item_def.get('advisory_range_max'), item_def.get('type'))
                            if range_error:
                                # Check if value is also outside allowed range
                                is_outside_allowed = False
                                if 'allowed_ranges' in item_def:
                                    allowed_error = self._validate_ranges(value, item_def['allowed_ranges'], item_def.get('type'))
                                    is_outside_allowed = allowed_error is not None
                                elif 'allowed_range_min' in item_def or 'allowed_range_max' in item_def:
                                    allowed_error = self._validate_range(value, item_def.get('allowed_range_min'), item_def.get('allowed_range_max'), item_def.get('type'))
                                    is_outside_allowed = allowed_error is not None
                                
                                # Adjust message wording: use "advised" if within allowed range, "allowed" if outside
                                if is_outside_allowed:
                                    # Value is outside allowed range - keep "allowed" wording
                                    message = f"Out of advisory range: {range_error}"
                                else:
                                    # Value is within allowed range but outside advisory - use "advised" wording
                                    message = f"Out of advisory range: {range_error.replace('allowed', 'advised')}"
                                
                                self.errors.append(self._create_validation_error(
                                    line_num=line_num,
                                    item_name=item_name,
                                    message=message,
                                    severity="warning",
                                global_column_index=global_column_index,
                                local_column_index=local_column_index,
                                value=value
                                ))
        
        # Validate parent/child category relationships
        self._validate_parent_child_relationships()
        
        # Validate oper_expression foreign key relationships
        self._validate_oper_expression_foreign_keys()
        
        return self.errors
    
    def _find_category_line(self, category: str) -> int:
        """Find the line number where a category appears."""
        for line_num, line in enumerate(self.mmcif.lines, 1):
            if f'_{category}.' in line:
                return line_num
        return 0
    
    def _find_item_value_line(self, item_name: str, value: str) -> int:
        """Find the line number where a specific item value appears."""
        if item_name in self.mmcif.items:
            for line_num, item_value, _, _ in self.mmcif.items[item_name]:
                if item_value == value:
                    return line_num
        return 0
    
    def _create_validation_error(self, line_num: int, item_name: str, message: str, severity: str, global_column_index: int = None, local_column_index: int = None, value: str = None) -> ValidationError:
        """Create a ValidationError with character position information if available."""
        start_char = None
        end_char = None
        
        # Use local_column_index to find the value position on the line
        # We know which column it is from the loop definition (global_column_index),
        # and local_column_index tells us its position on this specific line
        if local_column_index is not None:
            start_char, end_char = self._find_value_char_positions(line_num, local_column_index)
        
        return ValidationError(
            line=line_num,
            item=item_name,
            message=message,
            severity=severity,
            column=global_column_index,  # Store global column index for reference
            start_char=start_char,
            end_char=end_char
        )
    
    def _find_value_char_positions(self, line_num: int, local_column_index: int) -> Tuple[Optional[int], Optional[int]]:
        """Find the character start and end positions of a value on a line by its column index.
        
        Uses the exact same parsing logic as _parse_loop_line to ensure consistency.
        
        Args:
            line_num: Line number (1-based)
            local_column_index: Local column index (0-based) within this specific line
            
        Returns:
            Tuple of (start_char, end_char) positions, or (None, None) if not found
        """
        if line_num < 1 or line_num > len(self.mmcif.lines):
            return (None, None)
        
        line = self.mmcif.lines[line_num - 1]
        
        # Parse values from the line using the EXACT same logic as _parse_loop_line
        # Mirror the logic exactly, but track positions
        start_positions = []
        end_positions = []
        current = ""
        in_quotes = False
        quote_char = None
        value_start_char = None  # Character position where current value started
        
        i = 0
        while i < len(line):
            char = line[i]
            
            if not in_quotes:
                if char in ["'", '"']:
                    in_quotes = True
                    quote_char = char
                    value_start_char = i  # Opening quote position
                    # Don't include the opening quote in current (matches _parse_loop_line)
                elif char == ' ' or char == '\t':
                    if current.strip():
                        # End of unquoted value - same check as _parse_loop_line
                        # Calculate start position: where the value actually began
                        if value_start_char is not None:
                            start_pos = value_start_char
                        else:
                            # Value started when we first saw a non-space char
                            start_pos = i - len(current)
                        start_positions.append(start_pos)
                        end_positions.append(i)  # End before the space
                        current = ""
                        value_start_char = None
                else:
                    if value_start_char is None:
                        value_start_char = i
                    current += char
            else:
                if char == quote_char and (i == 0 or line[i-1] != '\\'):
                    # Closing quote - don't include it (matches _parse_loop_line)
                    in_quotes = False
                    quote_char = None
                    # Value ends at closing quote (include the quote for highlighting)
                    start_positions.append(value_start_char)  # Include opening quote
                    end_positions.append(i + 1)  # Include closing quote
                    current = ""
                    value_start_char = None
                else:
                    current += char
            
            i += 1
        
        # Handle last value if any (same as _parse_loop_line: if current.strip())
        if current.strip():
            if value_start_char is not None:
                start_positions.append(value_start_char)
            else:
                start_positions.append(len(line) - len(current))
            end_positions.append(len(line))
        
        # Use local_column_index to get the position
        # This should match exactly with how _parse_loop_line counts values
        if local_column_index < len(start_positions):
            return (start_positions[local_column_index], end_positions[local_column_index])
        
        return (None, None)
    
    def _validate_type(self, value: str, item_type: str) -> bool:
        """Validate a value against its expected type code."""
        if not value or value in ['?', '.']:
            return True  # Missing/unknown values are valid
        
        # First, check if we have a regex pattern from the dictionary
        if item_type in self.dictionary.type_regex_patterns:
            regex_pattern = self.dictionary.type_regex_patterns[item_type]
            try:
                # Compile and test the regex pattern
                # Always use anchors to ensure full value match (not partial)
                # Some patterns from the dictionary may already include anchors, so check
                if regex_pattern.startswith('^') and regex_pattern.endswith('$'):
                    # Pattern already has anchors
                    if re.match(regex_pattern, value):
                        return True
                else:
                    # Add anchors to ensure full match
                    pattern_with_anchors = f'^{regex_pattern}$'
                    if re.match(pattern_with_anchors, value):
                        return True
                return False
            except re.error as e:
                # If regex is invalid, fall through to hardcoded validation
                # This can happen if the dictionary has malformed regex patterns
                pass
        
        # Fall back to hardcoded validation for types without regex patterns
        # Date format: yyyy-mm-dd
        if item_type == 'yyyy-mm-dd':
            pattern = r'^\d{4}-\d{2}-\d{2}$'
            if not re.match(pattern, value):
                return False
            # Additional validation: check if it's a valid date
            try:
                parts = value.split('-')
                if len(parts) == 3:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    # Basic range checks
                    if month < 1 or month > 12 or day < 1 or day > 31:
                        return False
                    # More detailed validation using datetime
                    from datetime import datetime
                    datetime(year, month, day)
                    return True
            except (ValueError, TypeError):
                return False
            return False
        
        # Date-time format: yyyy-mm-dd:hh:mm
        elif item_type == 'yyyy-mm-dd:hh:mm':
            pattern = r'^\d{4}-\d{2}-\d{2}:\d{2}:\d{2}$'
            if not re.match(pattern, value):
                return False
            try:
                date_part, time_part = value.split(':')
                parts = date_part.split('-')
                if len(parts) == 3:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    hour, minute = int(time_part[:2]), int(time_part[2:])
                    if month < 1 or month > 12 or day < 1 or day > 31:
                        return False
                    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                        return False
                    from datetime import datetime
                    datetime(year, month, day, hour, minute)
                    return True
            except (ValueError, TypeError):
                return False
            return False
        
        # Date-time format with flexibility: yyyy-mm-dd:hh:mm-flex
        elif item_type == 'yyyy-mm-dd:hh:mm-flex':
            # More flexible format - allow partial times
            pattern = r'^\d{4}-\d{2}-\d{2}(:\d{2}(:\d{2})?)?$'
            if not re.match(pattern, value):
                return False
            try:
                if ':' in value:
                    date_part, time_part = value.split(':', 1)
                else:
                    date_part = value
                    time_part = None
                parts = date_part.split('-')
                if len(parts) == 3:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                    if month < 1 or month > 12 or day < 1 or day > 31:
                        return False
                    from datetime import datetime
                    if time_part:
                        if len(time_part) == 2:
                            hour = int(time_part)
                            if hour < 0 or hour > 23:
                                return False
                        elif len(time_part) == 5:
                            hour, minute = int(time_part[:2]), int(time_part[3:])
                            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                                return False
                    datetime(year, month, day)
                    return True
            except (ValueError, TypeError):
                return False
            return False
        
        # Integer type
        elif item_type == 'int' or item_type == 'positive_int':
            try:
                int_val = int(value)
                if item_type == 'positive_int' and int_val <= 0:
                    return False
                return True
            except ValueError:
                return False
        
        # Float type
        elif item_type == 'float' or item_type == 'float-range':
            try:
                float(value)
                return True
            except ValueError:
                return False
        
        # Boolean type
        elif item_type == 'boolean':
            return value.lower() in ['yes', 'no', 'y', 'n', 'true', 'false', '1', '0']
        
        # For other types (code, text, etc.), we don't validate format strictly
        # as they can have various valid formats
        return True
    
    def _validate_range(self, value: str, min_val: Optional[str], max_val: Optional[str], item_type: Optional[str]) -> Optional[str]:
        """Validate a value against its range constraints. Returns error message if invalid, None if valid."""
        if not value or value in ['?', '.']:
            return None  # Missing/unknown values are valid
        
        # Try to convert to numeric value for comparison
        try:
            # Determine if we should use int or float based on type or value format
            if item_type in ['int', 'positive_int'] or (item_type is None and '.' not in value and 'e' not in value.lower()):
                # Try integer first
                try:
                    num_value = int(value)
                except ValueError:
                    # If it's supposed to be int but can't parse, it's a type error, not range error
                    return None
            else:
                # Use float
                num_value = float(value)
            
            # Check minimum
            if min_val is not None:
                try:
                    min_num = float(min_val) if '.' in min_val or 'e' in min_val.lower() else int(min_val)
                    if num_value < min_num:
                        return f"Value '{value}' is below minimum allowed value '{min_val}'"
                except (ValueError, TypeError):
                    pass  # If we can't parse min_val, skip this check
            
            # Check maximum
            if max_val is not None:
                try:
                    max_num = float(max_val) if '.' in max_val or 'e' in max_val.lower() else int(max_val)
                    if num_value > max_num:
                        return f"Value '{value}' is above maximum allowed value '{max_val}'"
                except (ValueError, TypeError):
                    pass  # If we can't parse max_val, skip this check
            
        except (ValueError, TypeError):
            # If we can't convert value to number, it's not a range error
            # (it would be caught by type validation instead)
            return None
        
        return None  # Value is within range
    
    def _validate_ranges(self, value: str, ranges: List[Dict], item_type: Optional[str]) -> Optional[str]:
        """Validate a value against combined range constraints. Returns error message if invalid, None if valid.
        
        Ranges in a loop are combined (not alternatives):
        - Range with min==max means "exactly this value" (x = value)
        - Range with min and unbounded max means "x > min" (strictly greater)
        - Range with max and unbounded min means "x < max" (strictly less)
        - Combined: overall min <= x <= overall max
        
        Example: [., 1.0] and [1.0, 1.0] combine to mean "x >= 1.0"
        """
        if not value or value in ['?', '.']:
            return None  # Missing/unknown values are valid
        
        # Try to convert to numeric value for comparison
        try:
            # Determine if we should use int or float based on type or value format
            if item_type in ['int', 'positive_int'] or (item_type is None and '.' not in value and 'e' not in value.lower()):
                # Try integer first
                try:
                    num_value = int(value)
                except ValueError:
                    # If it's supposed to be int but can't parse, it's a type error, not range error
                    return None
            else:
                # Use float
                num_value = float(value)
            
            # Combine all ranges to find overall min and max bounds
            # Logic: ranges are combined (not alternatives)
            # - Range with min and unbounded max: "x > min" (strictly greater)
            # - Range with min==max: "x = value" (exactly equal)
            # - Combined: if we have both "x > min" and "x = min", then "x >= min"
            
            overall_min = None
            overall_max = None
            strict_min = None  # Strict > constraint (from unbounded max with min)
            strict_max = None  # Strict < constraint (from unbounded min with max)
            exact_values = set()  # Values that must be exactly equal (from min==max ranges)
            
            for range_def in ranges:
                min_val = range_def.get('min')
                max_val = range_def.get('max')
                
                try:
                    # Parse min and max values (handle '.' as unbounded)
                    min_num = None
                    max_num = None
                    
                    if min_val and min_val != '.':
                        min_num = float(min_val) if '.' in min_val or 'e' in min_val.lower() else int(min_val)
                    if max_val and max_val != '.':
                        max_num = float(max_val) if '.' in max_val or 'e' in max_val.lower() else int(max_val)
                    
                    # If min == max, this is an exact value constraint
                    if min_num is not None and max_num is not None and min_num == max_num:
                        exact_values.add(min_num)
                    else:
                        # Check for strict constraints (unbounded on one side)
                        if min_num is not None and max_val == '.':
                            # Unbounded max with min: "x > min" (strict)
                            if strict_min is None or min_num > strict_min:
                                strict_min = min_num
                        elif max_num is not None and min_val == '.':
                            # Unbounded min with max: "x < max" (strict)
                            if strict_max is None or max_num < strict_max:
                                strict_max = max_num
                        else:
                            # Bounded range: update overall bounds
                            if min_num is not None:
                                if overall_min is None or min_num < overall_min:
                                    overall_min = min_num
                            if max_num is not None:
                                if overall_max is None or max_num > overall_max:
                                    overall_max = max_num
                
                except (ValueError, TypeError):
                    continue  # Skip invalid range definition
            
            # Combine constraints:
            # If we have both strict_min and exact value at strict_min, it becomes >=
            # If we have strict_min but no exact value at strict_min, it stays >
            # If we have exact values at the boundaries of bounded ranges, boundaries are inclusive
            combined_min = overall_min
            combined_max = overall_max
            min_inclusive = True  # Whether min bound is inclusive (>=) or exclusive (>)
            max_inclusive = True  # Whether max bound is inclusive (<=) or exclusive (<)
            
            # If we have exact values at the boundaries of bounded ranges, ensure boundaries are inclusive
            if overall_min is not None and overall_min in exact_values:
                min_inclusive = True
            if overall_max is not None and overall_max in exact_values:
                max_inclusive = True
            
            if strict_min is not None:
                if strict_min in exact_values:
                    # We have both "x > strict_min" and "x = strict_min", so "x >= strict_min"
                    combined_min = strict_min
                    min_inclusive = True
                else:
                    # Only "x > strict_min", so it's exclusive
                    combined_min = strict_min
                    min_inclusive = False
                # Update if overall_min is more restrictive
                if overall_min is not None and overall_min > strict_min:
                    combined_min = overall_min
                    min_inclusive = True
                elif overall_min is not None and overall_min == strict_min:
                    # If they're equal and we have exact value, it's inclusive
                    if strict_min in exact_values:
                        min_inclusive = True
            
            if strict_max is not None:
                if strict_max in exact_values:
                    # We have both "x < strict_max" and "x = strict_max", so "x <= strict_max"
                    combined_max = strict_max
                    max_inclusive = True
                else:
                    # Only "x < strict_max", so it's exclusive
                    combined_max = strict_max
                    max_inclusive = False
                # Update if overall_max is more restrictive
                if overall_max is not None and overall_max < strict_max:
                    combined_max = overall_max
                    max_inclusive = True
                elif overall_max is not None and overall_max == strict_max:
                    # If they're equal and we have exact value, it's inclusive
                    if strict_max in exact_values:
                        max_inclusive = True
            
            # If we only have exact values (no ranges), value must match one of them
            if exact_values and combined_min is None and combined_max is None:
                if num_value not in exact_values:
                    exact_str = ', '.join(str(v) for v in sorted(exact_values))
                    return f"Value '{value}' must be exactly one of: {exact_str}"
                return None
            
            # Validate against combined bounds
            if combined_min is not None:
                if min_inclusive:
                    if num_value < combined_min:
                        return f"Value '{value}' is below minimum allowed value '{combined_min}'"
                else:
                    if num_value <= combined_min:
                        return f"Value '{value}' must be greater than '{combined_min}'"
            
            if combined_max is not None:
                if max_inclusive:
                    if num_value > combined_max:
                        return f"Value '{value}' is above maximum allowed value '{combined_max}'"
                else:
                    if num_value >= combined_max:
                        return f"Value '{value}' must be less than '{combined_max}'"
            
            # Value is within combined bounds - valid!
            return None
            
        except (ValueError, TypeError):
            # If we can't convert value to number, it's not a range error
            # (it would be caught by type validation instead)
            return None
    
    def _build_parent_composite_index(self, parent_cat: str, parent_items: List[str]) -> Set[Tuple[str, ...]]:
        """
        Build an index of parent rows as tuples.
        Returns: Set of tuples, each tuple contains values for parent_items in order.
        """
        # Check if parent items exist
        for item in parent_items:
            if item not in self.mmcif.items:
                return set()
        
        # Optimize: Build index directly from items without reconstructing all rows
        # This is much faster for large categories
        index = set()
        
        # Get value lists for each parent item
        item_value_lists = {}
        max_rows = 0
        for item in parent_items:
            if item in self.mmcif.items:
                values_list = self.mmcif.items[item]
                item_value_lists[item] = values_list
                max_rows = max(max_rows, len(values_list))
        
        # Build index by matching values at same index across items
        for row_idx in range(max_rows):
            row_values = []
            all_present = True
            for item in parent_items:
                if row_idx < len(item_value_lists[item]):
                    value = item_value_lists[item][row_idx][1]  # Get value (second element of tuple)
                    if value in ['?', '.']:
                        all_present = False
                        break
                    row_values.append(value)
                else:
                    all_present = False
                    break
            
            if all_present and len(row_values) == len(parent_items):
                index.add(tuple(row_values))
        
        return index
    
    def _validate_composite_key_relationship(self, link_group: List[Dict], child_cat: str, parent_cat: str, parent_index: Set[Tuple[str, ...]]):
        """
        Validate a composite key relationship where multiple child items together
        reference multiple parent items.
        
        Args:
            link_group: List of relationship dicts with same link_group_id
            child_cat: Child category name
            parent_cat: Parent category name
            parent_index: Pre-built index of parent composite keys (set of tuples)
        """
        # Extract child and parent items from link group
        child_items = [rel['child_item'] for rel in link_group]
        parent_items = [rel['parent_item'] for rel in link_group]
        
        # Check if parent category exists
        if parent_cat not in self.mmcif.categories:
            # Parent category missing - this is handled by existing validation
            return
        
        # Special handling for categories with both label and auth fields in the same composite key
        # These categories need to be validated separately: try label fields first, then auth fields if label is incomplete
        # This applies to: struct_conn, pdbx_struct_conn_angle, geom_*, atom_site_anisotrop, pdbx_atom_site_aniso_tls, etc.
        if parent_cat == 'atom_site' and self._has_both_label_and_auth_fields(link_group):
            self._validate_label_auth_composite_key(link_group, child_cat, parent_cat)
            return
        
        # If parent has no valid rows, skip validation
        if not parent_index:
            return
        
        # If parent has no valid rows, skip validation
        if not parent_index:
            return
        
        # Optimize: Check if child items exist and get their value lists
        child_item_lists = {}
        max_child_rows = 0
        for item in child_items:
            if item in self.mmcif.items:
                child_item_lists[item] = self.mmcif.items[item]
                max_child_rows = max(max_child_rows, len(self.mmcif.items[item]))
            else:
                # Child item missing - skip validation
                return
        
        # Validate each child row (by index, not by reconstructing all rows)
        for row_idx in range(max_child_rows):
            # Extract values for child_items in order
            child_values = []
            all_present = True
            for item in child_items:
                if row_idx < len(child_item_lists[item]):
                    value = child_item_lists[item][row_idx][1]  # Get value (second element of tuple)
                    if value in ['?', '.']:
                        all_present = False
                        break
                    child_values.append(value)
                else:
                    all_present = False
                    break
            
            if not all_present or len(child_values) != len(child_items):
                continue
            
            child_values = tuple(child_values)
            
            # Skip if any value is missing
            if any(v in ['?', '.'] for v in child_values):
                continue
            
            # Check if this combination exists in parent
            if child_values not in parent_index:
                # Find line number and column info for first child item
                first_child_item = child_items[0]
                if row_idx < len(child_item_lists[first_child_item]):
                    line_num, value, global_col, local_col = child_item_lists[first_child_item][row_idx]
                else:
                    line_num, value, global_col, local_col = (1, '', 0, 0)
                
                # Create error message showing which combination failed
                child_values_str = ', '.join(f"{child_items[i]}='{child_values[i]}'" for i in range(len(child_values)))
                parent_values_str = ', '.join(f"{parent_items[i]}" for i in range(len(parent_items)))
                
                self.errors.append(self._create_validation_error(
                    line_num=line_num,
                    item_name=first_child_item,
                    message=f"Composite key ({child_values_str}) does not exist in parent category '{parent_cat}' (expected combination of {parent_values_str})",
                    severity="error",
                    global_column_index=global_col,
                    local_column_index=local_col,
                    value=child_values[0]
                ))
    
    def _has_both_label_and_auth_fields(self, link_group: List[Dict]) -> bool:
        """Check if a link group has both label and auth fields."""
        has_label = any('label' in rel['child_item'].lower() for rel in link_group)
        has_auth = any('auth' in rel['child_item'].lower() for rel in link_group)
        return has_label and has_auth
    
    def _validate_label_auth_composite_key(self, link_group: List[Dict], child_cat: str, parent_cat: str):
        """
        Special validation for categories with both label and auth fields in the same composite key.
        The dictionary defines both label and auth fields together, but we need to validate them separately:
        try label fields first, then auth fields if label is incomplete.
        
        This applies to categories like: struct_conn, pdbx_struct_conn_angle, geom_*, atom_site_anisotrop, etc.
        
        Args:
            link_group: List of relationship dicts with same link_group_id
            child_cat: Child category name
            parent_cat: Parent category name (should be 'atom_site')
        """
        # Separate label and auth fields
        label_rels = []
        auth_rels = []
        
        for rel in link_group:
            child_item = rel['child_item']
            if 'label' in child_item.lower():
                label_rels.append(rel)
            elif 'auth' in child_item.lower():
                auth_rels.append(rel)
        
        # Core fields needed for atom identification (excluding alt_id and ins_code which are optional)
        # These patterns match various naming conventions: ptnr1_label_*, atom_site_label_*, label_*, etc.
        core_label_fields = ['label_asym_id', 'label_comp_id', 'label_seq_id', 'label_atom_id']
        core_auth_fields = ['auth_asym_id', 'auth_comp_id', 'auth_seq_id']
        # Note: auth_atom_id might not exist in the file, so we'll use label_atom_id as fallback for auth validation
        
        # Filter to core fields only
        label_rels_core = [r for r in label_rels if any(field in r['child_item'] for field in core_label_fields)]
        auth_rels_core = [r for r in auth_rels if any(field in r['child_item'] for field in core_auth_fields)]
        
        # Check if auth_atom_id exists in relationships, if not we'll use label_atom_id for auth validation
        auth_atom_id_rel = [r for r in auth_rels if 'auth_atom_id' in r['child_item']]
        use_label_atom_for_auth = len(auth_atom_id_rel) == 0
        
        # If auth_atom_id is missing, find the corresponding label_atom_id relationship
        label_atom_id_rel = None
        if use_label_atom_for_auth:
            # Find label_atom_id that matches the partner number (ptnr1, ptnr2, ptnr3)
            for rel in label_rels:
                if 'label_atom_id' in rel['child_item']:
                    # Extract partner number from the first auth field to match
                    if auth_rels_core:
                        first_auth_item = auth_rels_core[0]['child_item']
                        # Extract ptnr1/ptnr2/ptnr3 from auth item
                        if 'ptnr1' in first_auth_item and 'ptnr1' in rel['child_item']:
                            label_atom_id_rel = rel
                            break
                        elif 'ptnr2' in first_auth_item and 'ptnr2' in rel['child_item']:
                            label_atom_id_rel = rel
                            break
                        elif 'ptnr3' in first_auth_item and 'ptnr3' in rel['child_item']:
                            label_atom_id_rel = rel
                            break
        
        # Sort to ensure consistent order: asym_id, comp_id, seq_id, atom_id
        def sort_key(rel):
            item = rel['child_item']
            if 'asym_id' in item: return 0
            if 'comp_id' in item: return 1
            if 'seq_id' in item: return 2
            if 'atom_id' in item: return 3
            return 4
        
        label_rels_core.sort(key=sort_key)
        auth_rels_core.sort(key=sort_key)
        
        # If both label and auth core rels are empty, there's nothing to validate
        if not label_rels_core and not auth_rels_core:
            return
        
        # Build parent indexes for label and auth fields
        if label_rels_core:
            label_parent_items = [r['parent_item'] for r in label_rels_core]
            label_parent_index = self._build_parent_composite_index(parent_cat, label_parent_items)
        else:
            label_parent_index = set()
        
        # For auth fields, if auth_atom_id is missing, we need to use label_atom_id's parent
        if auth_rels_core:
            auth_parent_items = [r['parent_item'] for r in auth_rels_core]
            if use_label_atom_for_auth and label_atom_id_rel:
                # Add label_atom_id's parent item to the auth parent items
                auth_parent_items.append(label_atom_id_rel['parent_item'])
            auth_parent_index = self._build_parent_composite_index(parent_cat, auth_parent_items)
        else:
            auth_parent_index = set()
        
        # Get child item lists
        max_rows = 0
        all_child_items = {}
        for rel in link_group:
            item = rel['child_item']
            if item in self.mmcif.items:
                all_child_items[item] = self.mmcif.items[item]
                max_rows = max(max_rows, len(self.mmcif.items[item]))
        
        # Validate each row
        for row_idx in range(max_rows):
            # Try label fields first
            label_values = []
            label_complete = True
            for rel in label_rels_core:
                item = rel['child_item']
                if item in all_child_items and row_idx < len(all_child_items[item]):
                    value = all_child_items[item][row_idx][1]
                    if value in ['?', '.']:
                        label_complete = False
                        break
                    label_values.append(value)
                else:
                    label_complete = False
                    break
            
            if label_complete and len(label_values) == len(label_rels_core) and label_rels_core:
                # Check if label combination exists
                if tuple(label_values) not in label_parent_index:
                    first_item = label_rels_core[0]['child_item']
                    if row_idx < len(all_child_items[first_item]):
                        line_num, value, global_col, local_col = all_child_items[first_item][row_idx]
                    else:
                        line_num, value, global_col, local_col = (1, '', 0, 0)
                    
                    label_values_str = ', '.join(f"{label_rels_core[i]['child_item']}='{label_values[i]}'" for i in range(len(label_values)))
                    self.errors.append(self._create_validation_error(
                        line_num=line_num,
                        item_name=first_item,
                        message=f"Composite key ({label_values_str}) does not exist in parent category '{parent_cat}'",
                        severity="error",
                        global_column_index=global_col,
                        local_column_index=local_col,
                        value=label_values[0] if label_values else ''
                    ))
                continue  # Label validation succeeded, skip auth validation
            
            # If label fields are incomplete, try auth fields
            auth_values = []
            auth_complete = True
            for rel in auth_rels_core:
                item = rel['child_item']
                if item in all_child_items and row_idx < len(all_child_items[item]):
                    value = all_child_items[item][row_idx][1]
                    if value in ['?', '.']:
                        auth_complete = False
                        break
                    auth_values.append(value)
                else:
                    auth_complete = False
                    break
            
            # If auth_atom_id is missing, use label_atom_id instead
            if auth_complete and use_label_atom_for_auth and label_atom_id_rel:
                label_atom_item = label_atom_id_rel['child_item']
                if label_atom_item in all_child_items and row_idx < len(all_child_items[label_atom_item]):
                    atom_value = all_child_items[label_atom_item][row_idx][1]
                    if atom_value not in ['?', '.']:
                        auth_values.append(atom_value)
                    else:
                        auth_complete = False
                else:
                    auth_complete = False
            
            # Expected length: auth fields (3) + atom_id (1 if using label_atom_id, or 0 if auth_atom_id exists)
            expected_auth_len = len(auth_rels_core) + (1 if use_label_atom_for_auth and label_atom_id_rel else 0)
            if auth_complete and len(auth_values) == expected_auth_len and auth_rels_core:
                # Check if auth combination exists
                if tuple(auth_values) not in auth_parent_index:
                    first_item = auth_rels_core[0]['child_item']
                    if row_idx < len(all_child_items[first_item]):
                        line_num, value, global_col, local_col = all_child_items[first_item][row_idx]
                    else:
                        line_num, value, global_col, local_col = (1, '', 0, 0)
                    
                    auth_values_str = ', '.join(f"{auth_rels_core[i]['child_item']}='{auth_values[i]}'" for i in range(len(auth_values)))
                    self.errors.append(self._create_validation_error(
                        line_num=line_num,
                        item_name=first_item,
                        message=f"Composite key ({auth_values_str}) does not exist in parent category '{parent_cat}'",
                        severity="error",
                        global_column_index=global_col,
                        local_column_index=local_col,
                        value=auth_values[0] if auth_values else ''
                    ))
    
    def _validate_single_key_relationship(self, rel: Dict, category_item_values: Dict, present_categories: Set, atom_site_line_values: Dict, entity_types: Dict):
        """Validate a single-item foreign key relationship (existing logic)."""
        child_cat = rel['child_category']
        parent_cat = rel['parent_category']
        child_item = rel['child_item']
        parent_item = rel['parent_item']
        
        # Only validate if the child item actually exists and has values in the file
        # Skip if child item is not present or has no values
        if child_cat not in category_item_values or child_item not in category_item_values[child_cat]:
            return
        
        child_values = category_item_values[child_cat][child_item]
        if not child_values:
            # Child item exists but has no values (all missing/unknown) - skip validation
            return
        
        # Check 1: If child item has values, parent category should also be present
        if parent_cat not in present_categories:
            # Find the line number where a child value appears
            # Use the first value to find a line number
            first_value = next(iter(child_values))
            line_num = self._find_item_value_line(child_item, first_value)
            # Find the actual entry in items to get column indices
            global_column_index = None
            local_column_index = None
            if child_item in self.mmcif.items:
                for item_line_num, item_value, item_global_col, item_local_col in self.mmcif.items[child_item]:
                    if item_value == first_value and item_line_num == line_num:
                        global_column_index = item_global_col
                        local_column_index = item_local_col
                        break
            
            self.errors.append(self._create_validation_error(
                line_num=line_num if line_num > 0 else 1,
                item_name=child_item,
                message=f"Child item '{child_item}' has values but parent category '{parent_cat}' is missing",
                severity="error",
                global_column_index=global_column_index,
                local_column_index=local_column_index,
                value=first_value
            ))
        else:
            # Check 2: Validate foreign key references
            # Get all values from parent item
            if parent_cat in category_item_values and parent_item in category_item_values[parent_cat]:
                parent_values = category_item_values[parent_cat][parent_item]
                
                # If parent has no values, skip validation (category exists but is empty)
                if not parent_values:
                    return
                
                # Check each child value exists in parent
                for child_value in child_values:
                    if child_value not in parent_values:
                        # For atom_site foreign keys, check entity type to determine if validation applies
                        if child_cat == 'atom_site':
                            # Find which entity this value belongs to
                            # Look up the line number where this value appears
                            line_num = self._find_item_value_line(child_item, child_value)
                            if line_num > 0:
                                # Find the entity_id for this line in atom_site
                                entity_id_item = '_atom_site.label_entity_id'
                                if entity_id_item in atom_site_line_values and line_num in atom_site_line_values[entity_id_item]:
                                    entity_id = atom_site_line_values[entity_id_item][line_num]
                                    entity_type = entity_types.get(entity_id, '')
                                    
                                    # Polymer-specific categories should only validate for polymer entities
                                    if parent_cat in ['entity_poly_seq', 'pdbx_poly_seq_scheme']:
                                        if entity_type != 'polymer':
                                            # Non-polymer entity - skip validation (expected to not be in polymer categories)
                                            continue
                                    
                                    # Non-polymer categories should only validate for non-polymer entities
                                    if parent_cat == 'pdbx_entity_nonpoly':
                                        if entity_type not in ['non-polymer', 'water']:
                                            # Polymer entity - skip validation (expected to not be in non-polymer categories)
                                            continue
                        
                        # For non-atom_site or when entity type check doesn't apply, use simple heuristic
                        # Polymer-specific categories: entity_poly_seq, pdbx_poly_seq_scheme
                        if parent_cat in ['entity_poly_seq', 'pdbx_poly_seq_scheme'] and child_cat != 'atom_site':
                            # Skip validation - non-polymer entities are expected to not be in polymer categories
                            # This prevents false positives for ligands, water, etc.
                            continue
                        
                        # Find the line number and column indices where this value appears
                        line_num = self._find_item_value_line(child_item, child_value)
                        # Find the actual entry in items to get column indices
                        global_column_index = None
                        local_column_index = None
                        if child_item in self.mmcif.items:
                            for item_line_num, item_value, item_global_col, item_local_col in self.mmcif.items[child_item]:
                                if item_value == child_value and item_line_num == line_num:
                                    global_column_index = item_global_col
                                    local_column_index = item_local_col
                                    break
                        
                        self.errors.append(self._create_validation_error(
                            line_num=line_num if line_num > 0 else 1,
                            item_name=child_item,
                            message=f"Foreign key value '{child_value}' in '{child_item}' does not exist in parent item '{parent_item}' (parent category '{parent_cat}')",
                            severity="error",
                            global_column_index=global_column_index,
                            local_column_index=local_column_index,
                            value=child_value
                        ))
    
    def _validate_parent_child_relationships(self):
        """Validate parent/child category relationships and foreign key references."""
        # Build a map of categories present in the mmCIF file
        present_categories = self.mmcif.categories
        
        # Build a map of item values by category and item name
        # Format: {category: {item_name: set(values)}}
        category_item_values: Dict[str, Dict[str, Set[str]]] = {}
        # Also build a map of line -> value for atom_site to match values to entity_ids
        # Format: {item_name: {line_num: value}}
        atom_site_line_values: Dict[str, Dict[int, str]] = {}
        for item_name, values_list in self.mmcif.items.items():
            # Extract category from item name (format: _category.item_name)
            if item_name.startswith('_') and '.' in item_name:
                category = item_name[1:].split('.')[0]
                if category not in category_item_values:
                    category_item_values[category] = {}
                # Collect all non-missing values for this item
                item_values = {val for _, val, _, _ in values_list if val not in ['?', '.']}
                category_item_values[category][item_name] = item_values
                
                # For atom_site, also track line-by-line values for entity matching
                if category == 'atom_site':
                    atom_site_line_values[item_name] = {line_num: val for line_num, val, _, _ in values_list if val not in ['?', '.']}
        
        # Build entity_id -> entity_type map
        entity_types: Dict[str, str] = {}
        if 'entity' in category_item_values:
            entity_id_item = '_entity.id'
            entity_type_item = '_entity.type'
            if entity_id_item in category_item_values['entity'] and entity_type_item in category_item_values['entity']:
                # Match entity IDs with their types by position in loops
                # This assumes same order - in reality we'd need proper loop matching
                entity_ids = list(category_item_values['entity'][entity_id_item])
                entity_type_vals = list(category_item_values['entity'][entity_type_item])
                # Try to match by finding corresponding values in the parsed items
                # Get all entity.id and entity.type values with their line numbers
                entity_id_lines = {line_num: val for item_name, values_list in self.mmcif.items.items() 
                                  if item_name == entity_id_item for line_num, val, _, _ in values_list if val not in ['?', '.']}
                entity_type_lines = {line_num: val for item_name, values_list in self.mmcif.items.items() 
                                    if item_name == entity_type_item for line_num, val, _, _ in values_list if val not in ['?', '.']}
                # Match by line number (same line = same entity)
                for line_num in entity_id_lines:
                    if line_num in entity_type_lines:
                        entity_types[entity_id_lines[line_num]] = entity_type_lines[line_num]
        
        # Group relationships by (child_cat, parent_cat, link_group_id)
        link_groups: Dict[Tuple[str, str, str], List[Dict]] = {}
        for rel in self.dictionary.parent_child_relationships:
            key = (rel['child_category'], rel['parent_category'], rel['link_group_id'])
            if key not in link_groups:
                link_groups[key] = []
            link_groups[key].append(rel)
        
        # Cache for parent composite indexes to avoid rebuilding for the same (parent_cat, parent_items)
        parent_index_cache: Dict[Tuple[str, Tuple[str, ...]], Set[Tuple[str, ...]]] = {}
        
        # Validate each link group
        for (child_cat, parent_cat, link_group_id), relationships in link_groups.items():
            if len(relationships) == 1:
                # Single item - use existing validation
                rel = relationships[0]
                self._validate_single_key_relationship(rel, category_item_values, present_categories, atom_site_line_values, entity_types)
            else:
                # Multiple items - use composite key validation
                # Use cached parent index if available (order matters for composite keys!)
                parent_items = tuple([rel['parent_item'] for rel in relationships])
                cache_key = (parent_cat, parent_items)
                if cache_key not in parent_index_cache:
                    parent_index_cache[cache_key] = self._build_parent_composite_index(parent_cat, list(parent_items))
                self._validate_composite_key_relationship(relationships, child_cat, parent_cat, parent_index_cache[cache_key])
    
    def _validate_oper_expression_foreign_keys(self):
        """Validate that oper_expression values reference valid pdbx_struct_oper_list.id values.
        
        Operation expressions can have forms:
        - 1 (single operation)
        - (1,2,5) (multiple operations)
        - (1-4) (range of operations: 1,2,3,4)
        - (1,2)(3,4) (combinations)
        """
        oper_expression_item = '_pdbx_struct_assembly_gen.oper_expression'
        oper_list_id_item = '_pdbx_struct_oper_list.id'
        
        # Check if both items exist in the file
        if oper_expression_item not in self.mmcif.items:
            return
        
        if oper_list_id_item not in self.mmcif.items:
            # If oper_list doesn't exist, we can't validate - skip
            return
        
        # Get all valid operation IDs from pdbx_struct_oper_list
        valid_oper_ids = set()
        for _, oper_id, _, _ in self.mmcif.items[oper_list_id_item]:
            if oper_id not in ['?', '.']:
                valid_oper_ids.add(oper_id)
        
        # If no valid operation IDs exist, skip validation
        if not valid_oper_ids:
            return
        
        # Validate each oper_expression value
        for line_num, oper_expr, global_column_index, local_column_index in self.mmcif.items[oper_expression_item]:
            if oper_expr in ['?', '.']:
                continue  # Skip missing/unknown values
            
            # Parse the operation expression to extract all referenced IDs
            referenced_ids = self._parse_oper_expression(oper_expr)
            
            # Check each referenced ID exists in pdbx_struct_oper_list
            for oper_id in referenced_ids:
                if oper_id not in valid_oper_ids:
                    self.errors.append(self._create_validation_error(
                        line_num=line_num,
                        item_name=oper_expression_item,
                        message=f"Operation expression '{oper_expr}' references operation ID '{oper_id}' which does not exist in '_pdbx_struct_oper_list.id'. Valid IDs: {sorted(valid_oper_ids, key=lambda x: (len(x), x))}",
                        severity="error",
                        global_column_index=global_column_index,
                        local_column_index=local_column_index,
                        value=oper_expr
                    ))
    
    def _parse_oper_expression(self, expr: str) -> Set[str]:
        """Parse an operation expression and extract all referenced operation IDs.
        
        Examples:
        - "1" -> {"1"}
        - "(1,2,5)" -> {"1", "2", "5"}
        - "(1-4)" -> {"1", "2", "3", "4"}
        - "(1,2)(3,4)" -> {"1", "2", "3", "4"}
        """
        referenced_ids = set()
        
        # Remove whitespace
        expr = expr.strip()
        
        # Handle simple case: just a number (no parentheses)
        if not expr.startswith('('):
            # Try to parse as a single number
            if expr.isdigit():
                referenced_ids.add(expr)
            return referenced_ids
        
        # Parse parenthesized groups
        # Pattern: (1,2,5) or (1-4) or (1,2)(3,4)
        # Use regex to find all parenthesized groups
        group_pattern = r'\(([^)]+)\)'
        groups = re.findall(group_pattern, expr)
        
        for group in groups:
            # Check if it's a range (e.g., "1-4")
            if '-' in group:
                range_parts = group.split('-', 1)
                if len(range_parts) == 2:
                    try:
                        start = int(range_parts[0].strip())
                        end = int(range_parts[1].strip())
                        # Add all IDs in the range
                        for i in range(start, end + 1):
                            referenced_ids.add(str(i))
                    except ValueError:
                        # Invalid range format - skip
                        pass
            else:
                # Comma-separated list (e.g., "1,2,5")
                ids = [id_str.strip() for id_str in group.split(',')]
                for oper_id in ids:
                    if oper_id.isdigit():
                        referenced_ids.add(oper_id)
        
        return referenced_ids


def download_dictionary(url: str) -> Path:
    """Download dictionary from URL and return path to temporary file."""
    print(f"Downloading dictionary from {url}...")
    try:
        with urllib.request.urlopen(url) as response:
            # Create a temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.dic', delete=False, encoding='utf-8') as tmp_file:
                # Read and write in chunks to handle large files
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    tmp_file.write(chunk.decode('utf-8', errors='replace'))
                tmp_path = Path(tmp_file.name)
        print(f"Dictionary downloaded to temporary file: {tmp_path}")
        return tmp_path
    except urllib.error.URLError as e:
        print(f"Error downloading dictionary: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing downloaded dictionary: {e}")
        sys.exit(1)


def main():
    """Main entry point for the validator."""
    # Ensure unbuffered output for proper redirection support
    import sys
    import os
    
    # Force line-buffered output when redirected (not a TTY)
    # This prevents hanging when redirecting output to a file
    if not sys.stdout.isatty():
        try:
            # Python 3.7+: Use reconfigure for line buffering
            sys.stdout.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            # Fallback: Reopen stdout with line buffering
            try:
                sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
            except (OSError, ValueError):
                # If that fails, we'll rely on explicit flushing in print statements
                pass
    
    parser = argparse.ArgumentParser(
        description='Validate mmCIF files against a dictionary',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use local dictionary file
  validate_mmcif.py --file mmcif_pdbx_v5_next.dic 9rff.cif
  
  # Use dictionary from URL
  validate_mmcif.py --url http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 9rff.cif
  
  # Auto-detect (file path or URL) - backward compatible
  validate_mmcif.py mmcif_pdbx_v5_next.dic 9rff.cif
  validate_mmcif.py http://mmcif.pdb.org/dictionaries/ascii/mmcif_pdbx.dic 9rff.cif
        """
    )
    
    # Dictionary source options (mutually exclusive)
    dict_group = parser.add_mutually_exclusive_group()
    dict_group.add_argument(
        '--file', '-f',
        type=str,
        help='Path to local dictionary file (.dic)'
    )
    dict_group.add_argument(
        '--url', '-u',
        type=str,
        help='URL to download dictionary from'
    )
    
    # Positional arguments (for backward compatibility)
    parser.add_argument(
        'dict_source',
        nargs='?',
        help='Dictionary file path or URL (if --file or --url not specified)'
    )
    parser.add_argument(
        'cif_file',
        help='mmCIF file to validate (.cif)'
    )
    
    args = parser.parse_args()
    
    # Determine dictionary source
    if args.file:
        dict_source = args.file
        is_url = False
    elif args.url:
        dict_source = args.url
        is_url = True
    elif args.dict_source:
        dict_source = args.dict_source
        # Auto-detect if it's a URL
        is_url = dict_source.startswith('http://') or dict_source.startswith('https://')
    else:
        parser.error("Either specify --file, --url, or provide dictionary source as positional argument")
    
    cif_path = Path(args.cif_file)
    
    # Get dictionary file
    if is_url:
        dict_path = download_dictionary(dict_source)
        cleanup_temp_file = True
    else:
        dict_path = Path(dict_source)
        cleanup_temp_file = False
    
    if not dict_path.exists():
        print(f"Error: Dictionary file not found: {dict_path}")
        sys.exit(1)
    
    if not cif_path.exists():
        print(f"Error: mmCIF file not found: {cif_path}")
        if cleanup_temp_file:
            dict_path.unlink()  # Clean up temp file
        sys.exit(1)
    
    # Parse dictionary
    print(f"Parsing dictionary: {dict_path}")
    dictionary = DictionaryParser(dict_path)
    dictionary.parse()
    print(f"Loaded {len(dictionary.items)} items from dictionary")
    
    # Parse mmCIF file
    print(f"Parsing mmCIF file: {cif_path}")
    mmcif = MmCIFParser(cif_path)
    mmcif.parse()
    print(f"Found {len(mmcif.items)} items in mmCIF file")
    
    # Validate
    print("Validating...")
    validator = MmCIFValidator(dictionary, mmcif)
    errors = validator.validate()
    
    # Output results
    if errors:
        print(f"\nFound {len(errors)} validation issue(s):\n")
        for error in errors:
            print(f"{error.severity.upper()}: Line {error.line}, Item '{error.item}'")
            print(f"  {error.message}\n")
        
        # Output JSON for VSCode extension
        json_output = {
            'errors': [
                {
                    'line': err.line,
                    'item': err.item,
                    'message': err.message,
                    'severity': err.severity,
                    'column': err.column,
                    'start_char': err.start_char,
                    'end_char': err.end_char
                }
                for err in errors
            ]
        }
        print(json.dumps(json_output, indent=2))
        if cleanup_temp_file:
            dict_path.unlink()  # Clean up temp file
        sys.exit(1)
    else:
        print("\nValidation passed! No errors found.")
        if cleanup_temp_file:
            dict_path.unlink()  # Clean up temp file
        sys.exit(0)


if __name__ == '__main__':
    main()

