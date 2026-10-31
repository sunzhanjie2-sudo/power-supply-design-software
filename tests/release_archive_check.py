"""Read each final ZIP, compare every file against its included SHA256 list."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

def check(folder,expected_count=3):
    results=[]
    for path in sorted(Path(folder).glob('*.zip')):
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        assert actual.lower()==Path(str(path)+'.sha256').read_text().strip().lower(),path
        with ZipFile(path) as archive:
            files={name for name in archive.namelist() if not name.endswith('/')}
            roots={PurePosixPath(name).parts[0] for name in files}
            assert len(roots)==1,(path,roots)
            root=roots.pop()
            manifest=json.loads(archive.read(root+'/manifest.json').decode('utf-8-sig'))
            expected={root+'/manifest.json'}
            for entry in manifest['files']:
                relative=entry['path'].replace('\\','/')
                parts=PurePosixPath(relative).parts
                assert not PurePosixPath(relative).is_absolute() and '..' not in parts
                assert parts[0] not in ('data','user_data','.git','.venv-web','node_modules')
                name=root+'/'+relative;expected.add(name)
                assert archive.getinfo(name).file_size==entry['bytes'],name
                with archive.open(name) as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
                assert digest.lower()==entry['sha256'].lower(),name
            assert files==expected,(path,files^expected)
            results.append(dict(zip=path.name,files=len(files),bytes=path.stat().st_size,verified=True))
    assert len(results)==expected_count,f'Expected {expected_count} ZIPs, got {len(results)}'
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder');parser.add_argument('--expected-count',type=int,default=3)
    args=parser.parse_args();check(args.folder,args.expected_count)
