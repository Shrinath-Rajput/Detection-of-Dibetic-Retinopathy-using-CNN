import ast

def extract_keys(path):
    with open(path, encoding='utf-8') as f:
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
    return keys

if __name__ == '__main__':
    keys = extract_keys('app.py')
    print('keys_count', len(keys))
    for k in sorted(keys):
        print(repr(k))
