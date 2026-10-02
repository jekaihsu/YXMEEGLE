import ast
import textwrap
from scripts import formal_volume_preflight as probe


def test_remote_uid_child_compiles_after_outer_indentation():
    wrapped='import json\ntry:\n'+textwrap.indent(probe.REMOTE,' ')+'\nexcept Exception: pass\n'
    tree=ast.parse(wrapped)
    children=[node.value.value for node in ast.walk(tree) if isinstance(node,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='child' for t in node.targets)]
    assert len(children)==1
    compile(textwrap.dedent(children[0]),'uid-child','exec')
    assert '__import__(\'textwrap\').dedent(child)' in probe.REMOTE


def test_probe_is_fixed_and_never_changes_remote_volume():
    assert probe.SERVICE=='6ab61834a4c05a5bcb57ad69'
    assert "root=Path('/data/uploads')" in probe.REMOTE
    assert 'os.setgid(10001);os.setuid(10001)' in probe.REMOTE
    for mutation in ('os.chown','os.chmod','write_text','mkdir','unlink','remove('):
        assert mutation not in probe.REMOTE
