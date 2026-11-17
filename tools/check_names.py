"""静态检查：找出「引用了但从未定义/导入」的全局名字。

这类错误在 Qt 槽函数里会被 Qt 静默吞掉（只往 stderr 打一行 traceback），
表现就是界面上一直停在「读取中…」。pyflakes 不在这个解释器里，就自己写。

跑法：python tools/check_names.py
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Scope:
    def __init__(self, kind: str, parent: "Scope | None") -> None:
        self.kind = kind
        self.parent = parent
        self.names: set[str] = set()
        self.globals: set[str] = set()


def module_bindings(tree: ast.Module) -> set[str]:
    """模块顶层（含 if/try 分支）绑定到的名字。"""
    out: set[str] = set()

    def walk(nodes):
        for n in nodes:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    out.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(n.name)
                body = getattr(n, "body", [])
                # 只看 def 内部顶层语句里的 import（函数内 import 是局部作用域，跳过）
                if isinstance(n, ast.ClassDef):
                    walk(body)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    for name in ast.walk(t):
                        if isinstance(name, ast.Name):
                            out.add(name.id)
            elif isinstance(n, ast.AnnAssign):
                if isinstance(n.target, ast.Name):
                    out.add(n.target.id)
            elif isinstance(n, ast.For):
                for name in ast.walk(n.target):
                    if isinstance(name, ast.Name):
                        out.add(name.id)
                walk(n.body)
                walk(n.orelse)
            elif isinstance(n, (ast.If, ast.While)):
                walk(n.body)
                walk(n.orelse)
            elif isinstance(n, ast.Try):
                walk(n.body)
                for h in n.handlers:
                    if h.name:
                        out.add(h.name)
                    walk(h.body)
                walk(n.orelse)
                walk(n.finalbody)
            elif isinstance(n, ast.With):
                for item in n.items:
                    if item.optional_vars is not None:
                        for name in ast.walk(item.optional_vars):
                            if isinstance(name, ast.Name):
                                out.add(name.id)
                walk(n.body)

    walk(tree.body)
    return out


def collect_local(fn: ast.AST) -> set[str]:
    """函数体内部绑定的名字（参数、赋值、for、with、import、嵌套 def/class…）。"""
    out: set[str] = set()
    args = fn.args
    for a in (
        list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    ):
        out.add(a.arg)
    if args.vararg:
        out.add(args.vararg.arg)
    if args.kwarg:
        out.add(args.kwarg.arg)

    for n in ast.walk(fn):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
    return out


def check_file(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno} 语法错误 {exc.msg}"]

    mod_names = module_bindings(tree)
    problems: list[str] = []
    known = set(dir(builtins)) | mod_names

    class Walker(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[set[str]] = []

        def _scope_names(self) -> set[str]:
            acc: set[str] = set()
            for s in self.stack:
                acc |= s
            return acc

        def visit_FunctionDef(self, node):
            local = collect_local(node)
            self.stack.append(local)
            for d in list(node.decorator_list) + node.args.defaults:
                self.visit(d)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def _visit_comp(self, node):
            # 推导式在自己的作用域里绑定循环变量
            extra: set[str] = set()
            for gen in node.generators:
                for n in ast.walk(gen.target):
                    if isinstance(n, ast.Name):
                        extra.add(n.id)
            self.stack.append(extra)
            self.generic_visit(node)
            self.stack.pop()

        visit_ListComp = _visit_comp
        visit_SetComp = _visit_comp
        visit_DictComp = _visit_comp
        visit_GeneratorExp = _visit_comp

        def visit_Lambda(self, node):
            # lambda 的参数是 ast.arg，不是 Name(Store)，单独收
            a = node.args
            extra = {x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
            if a.vararg:
                extra.add(a.vararg.arg)
            if a.kwarg:
                extra.add(a.kwarg.arg)
            self.stack.append(extra)
            self.generic_visit(node)
            self.stack.pop()

        def visit_ClassDef(self, node):
            self.stack.append(set())
            self.generic_visit(node)
            self.stack.pop()

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                ident = node.id
                if ident in ("__file__", "__name__", "__doc__"):
                    return
                if ident in known or ident in self._scope_names():
                    return
                # 类体里引用自身类名等少数情况，交给运行期
                problems.append(f"{path}:{node.lineno} 未定义名字 {ident}")

    Walker().visit(tree)
    return problems


def main() -> int:
    targets: list[Path] = []
    for d in ("app", "tools"):
        targets.extend(sorted((ROOT / d).rglob("*.py")))
    targets.append(ROOT / "main.py")

    all_problems: list[str] = []
    for p in targets:
        if "__pycache__" in p.parts:
            continue
        all_problems.extend(check_file(p))

    if all_problems:
        print(f"发现 {len(all_problems)} 处问题：")
        for line in all_problems:
            print("  " + line)
        return 1
    print(f"✓ 扫描 {len(targets)} 个文件，没有未定义名字")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
