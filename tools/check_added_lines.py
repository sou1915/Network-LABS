"""Review-friendliness check for the Python lines a change adds; existing lines are left alone.

Flags, on added lines only:
  * more than one statement on a line (``a = 1; b = 2`` or ``if x: y``);
  * lines longer than MAX_LENGTH characters.

Usage: python3 tools/check_added_lines.py [--warn-only] BASE_REF   (e.g. origin/main)
Exit status 1 when an added line breaks a rule, unless --warn-only. Under GitHub Actions
each problem is also emitted as an annotation on the pull request line.
"""
import ast
import io
import os
import re
import subprocess
import sys
import tokenize

MAX_LENGTH = 140
COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.FunctionDef,
            ast.AsyncFunctionDef, ast.ClassDef)


def added_lines(base):
    """{path: {line numbers added in the working tree relative to the merge base with BASE}}."""
    diff = subprocess.run(['git', 'diff', '--unified=0', '--no-color', base + '...', '--', '*.py'],
                          capture_output=True, text=True, check=True).stdout
    result, path = {}, None
    for line in diff.splitlines():
        if line.startswith('+++ '):
            path = None if line == '+++ /dev/null' else line[6:]
        elif line.startswith('@@') and path:
            match = re.match(r'@@ -\S+ \+(\d+)(?:,(\d+))? @@', line)
            start, count = int(match[1]), int(match[2] or 1)
            result.setdefault(path, set()).update(range(start, start + count))
    return result


def problems(source, lines):
    found = []
    for number, text in enumerate(source.splitlines(), 1):
        if number in lines and len(text) > MAX_LENGTH:
            found.append((number, f'line is {len(text)} characters (limit {MAX_LENGTH})'))
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.OP and token.string == ';' and token.start[0] in lines:
            found.append((token.start[0], 'several statements joined with ";"'))
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, COMPOUND) and node.body and node.body[0].lineno == node.lineno and node.lineno in lines:
            found.append((node.lineno, f'{type(node).__name__.lower()} body on the same line as its header'))
    return sorted(set(found))


def main(arguments):
    warn_only = '--warn-only' in arguments
    arguments = [a for a in arguments if a != '--warn-only']
    if len(arguments) != 1:
        print(__doc__)
        return 2
    annotate = os.environ.get('GITHUB_ACTIONS') == 'true'
    failures = 0
    for path, lines in sorted(added_lines(arguments[0]).items()):
        try:
            with open(path, encoding='utf-8') as handle:
                source = handle.read()
        except FileNotFoundError:
            continue
        for number, message in problems(source, lines):
            print(f'{path}:{number}: {message}')
            if annotate:
                print(f'::{"warning" if warn_only else "error"} file={path},line={number}::{message}')
            failures += 1
    print(f'{failures} problem(s) on added lines.' if failures else 'Added lines pass.')
    return 1 if failures and not warn_only else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
