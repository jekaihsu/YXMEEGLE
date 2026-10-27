from pathlib import Path
import subprocess, json, sys, os
root=Path(__file__).resolve().parents[2]
mode=sys.argv[1]
front=root/'frontend'
if mode=='base':
    base=root/'.runtime/qa/base';base.mkdir(exist_ok=True)
    archive=subprocess.run(['git','archive','9f92eb4'],cwd=root,capture_output=True,check=True)
    subprocess.run(['tar','-x','-C',str(base)],input=archive.stdout,cwd=root,check=True)
    front=base/'frontend'
    (front/'node_modules').unlink(missing_ok=True)
    (front/'node_modules').symlink_to(root/'frontend/node_modules',target_is_directory=True)
build_dir=root/'.runtime/qa'/f'{mode}-dist'
result=subprocess.run(['node',str(root/'frontend/node_modules/vite/bin/vite.js'),'build','--outDir',str(build_dir)],cwd=front,capture_output=True,text=True)
(root/'output/qa-fixes-ui'/f'{mode}-build.txt').write_text(result.stdout+result.stderr)
result.check_returncode()
dist=front/'dist'
created_link=not dist.exists()
if created_link:dist.symlink_to(build_dir,target_is_directory=True)
results={}
out=root/'output/qa-fixes-ui'/mode;out.mkdir(exist_ok=True)
for test in sorted(front.glob('test-*.mjs')):
    try:
        p=subprocess.run(['node',str(test)],cwd=front,capture_output=True,text=True,timeout=50)
        results[test.name]=p.returncode
        (out/(test.stem+'.txt')).write_text(p.stdout+p.stderr)
    except subprocess.TimeoutExpired:
        results[test.name]='timeout'
(out/'results.json').write_text(json.dumps(results,indent=2))
print(json.dumps({'mode':mode,'files':len(results),'failures':{k:v for k,v in results.items() if v!=0}},indent=2))

if created_link:dist.unlink()
