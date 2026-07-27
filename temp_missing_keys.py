import json
import re
import os
import glob

import ast

with open('app.py', encoding='utf-8') as f:
    src = f.read()
mod = ast.parse(src)
keys = set()

class Visitor(ast.NodeVisitor):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in ('trans', 't', 'get_translation'):
            if node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.add(arg.value)
        self.generic_visit(node)

Visitor().visit(mod)

def flatten(obj, prefix=''):
    result = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            result.update(flatten(v, prefix + k + '.'))
    else:
        result[prefix[:-1]] = obj
    return result

locales = {}
for path in glob.glob('translations/*.json'):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    locales[os.path.splitext(os.path.basename(path))[0]] = flatten(data)

print('keys_count', len(keys))
for key in sorted(keys):
    missing = [loc for loc, d in locales.items() if key not in d]
    if missing:
        print('MISSING', key, missing)
