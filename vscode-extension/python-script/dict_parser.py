"""
Dictionary parser for mmCIF dictionary files.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Set


class DictionaryParser:
    """Parses mmCIF dictionary files."""
    
    def __init__(self, dict_path: Path):
        self.dict_path = dict_path
        self.items: Dict[str, Dict] = {}
        self.categories: Dict[str, Dict] = {}
        self.mandatory_items: Set[str] = set()
        # Deposition mandatory: for PDB deposition, use _pdbx_item.mandatory_code when present, else _item.mandatory_code
        # Maps category_id -> set of full item names (e.g. _pdbx_contact_author.id)
        self.deposition_mandatory_items: Dict[str, Set[str]] = {}
        self.parent_child_relationships: List[Dict] = []  # List of {child_cat, parent_cat, child_item, parent_item}
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
                    # Deposition mandatory: _pdbx_item.mandatory_code yes, or _item.mandatory_code yes if no _pdbx_item
                    pdbx_mandatory = item_info.get('pdbx_mandatory')
                    if pdbx_mandatory == 'yes' or (pdbx_mandatory is None and item_info.get('mandatory') == 'yes'):
                        cat = item_info.get('category')
                        if cat:
                            if cat not in self.deposition_mandatory_items:
                                self.deposition_mandatory_items[cat] = set()
                            self.deposition_mandatory_items[cat].add(item_name)
            
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

        # Extract PDBx deposition mandatory code (used for deposition-readiness; takes precedence when present)
        pdbx_mandatory_match = re.search(r'_pdbx_item\.mandatory_code\s+(\w+)', content)
        if pdbx_mandatory_match:
            item_info['pdbx_mandatory'] = pdbx_mandatory_match.group(1).strip()
        
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
