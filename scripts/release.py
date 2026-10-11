"""Source release. With Git, package exactly HEAD and create a portable bundle.

Without Git (tools container), package the mounted source without claiming a
commit identity. Never include credentials, runtime databases or recursive zips.
"""
from pathlib import Path
import hashlib,json,shutil,subprocess,zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'dist/downloads';OUT.mkdir(parents=True,exist_ok=True)
def permitted(path):
    parts=Path(path).parts
    return bool(parts) and parts[0] not in ('.git','.openai','.venv','artifacts') and not path.startswith('dist/downloads/') and '__pycache__' not in parts and not Path(path).name.startswith('.env') and Path(path).suffix not in ('.pyc','.sqlite','.log','.pem','.key')
commit=None
if shutil.which('git'):
    head=subprocess.run(['git','rev-parse','--verify','HEAD'],cwd=ROOT,text=True,capture_output=True)
    if head.returncode==0:
        commit=head.stdout.strip()
        files=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD'],cwd=ROOT,text=True).splitlines()
    else:files=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()]
else:files=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()]
files=sorted(p for p in files if permitted(p))
if '.env.example' not in files:files.append('.env.example')
archive=OUT/'sovereign-federation-lab.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for path in files:
        data=subprocess.check_output(['git','show','HEAD:'+path],cwd=ROOT) if commit else (ROOT/path).read_bytes()
        info=zipfile.ZipInfo('sovereign-federation-lab/'+path,date_time=(2026,10,11,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
        info.external_attr=(0o100755 if path=='lab' or path.endswith('.sh') else 0o100644)<<16
        z.writestr(info,data)
    z.writestr('sovereign-federation-lab/RELEASE.json',json.dumps({'commit':commit,'file_count':len(files),'database':'cockroach','container_acceptance':'See TESTING.md and docs/CONTAINER_ACCEPTANCE.md; packaging does not execute acceptance'},indent=2)+'\n')
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
shutil.copy2(archive,OUT/'sovereign-data-poc.zip') # Existing monitor download links remain valid.
paths=[archive]
if commit:
    bundle=OUT/'sovereign-federation-lab.bundle'
    subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True)
    subprocess.run(['git','bundle','verify',str(bundle)],cwd=ROOT,check=True,capture_output=True)
    paths.append(bundle)
manifest={'commit':commit,'file_count':len(files),'files':[{ 'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
(OUT/'release.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest,indent=2))
