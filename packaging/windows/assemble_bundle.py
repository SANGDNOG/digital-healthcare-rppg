from pathlib import Path
import json,hashlib,shutil,zipfile,sys
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'packaging/windows'));from build_package import build
out=root/'runs/windows-teammate-20261028';out.mkdir(exist_ok=True);package=out/'rPPG-Windows'
v=root/'workspace/windows-package-20261028/vendor'
build(root,package,v/'uv.exe',[v/'uv-LICENSE-MIT',v/'uv-LICENSE-APACHE'])
shutil.copy2(package/'start.cmd',package/'실험 시작.cmd')
for name in ['먼저 읽어주세요.txt','먼저 읽어주세요.html']:shutil.copy2(root/'packaging/windows'/name,package/name)
reports=package/'reports';reports.mkdir()
for name in ['index.html','멘토보고서_별첨.pdf','멘토보고서_별첨.txt','feedback-request.html','멘토_피드백_상세요청서.pdf','멘토_피드백_상세요청서.txt']:shutil.copy2(root/'docs/mentor-report-20261028'/name,reports/name)
meta=json.loads((package/'package.json').read_text());meta['included_reports']=sorted(p.name for p in reports.iterdir());meta['uv_download_url']='https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-pc-windows-msvc.zip';meta['uv_download_archive_sha256']='a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f';(package/'package.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
sha=lambda b:hashlib.sha256(b).hexdigest()
files=sorted(p for p in package.rglob('*') if p.is_file() and p.name!='SHA256SUMS');(package/'SHA256SUMS').write_text(''.join(sha(p.read_bytes())+'  '+p.relative_to(package).as_posix()+'\n' for p in files))
zpath=out/'rPPG_Windows_팀원용_2026-10-28.zip'
with zipfile.ZipFile(zpath,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(package.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(out))
with zipfile.ZipFile(zpath) as z:assert z.testzip() is None
receipt={'zip':str(zpath),'sha256':sha(zpath.read_bytes()),'bytes':zpath.stat().st_size,'files':len(files)+1,'runtime_id':meta['runtime_id'],'source_commit':meta['source_commit']};(out/'verification.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
