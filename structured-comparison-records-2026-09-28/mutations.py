import io,json,types,unittest
from pathlib import Path
from unittest.mock import patch
import version_comparison as v
from test_version_comparison import VersionTests
source=Path('version_comparison.py').read_text()
mutations={
 'erase_operators':source.replace("if value['operator']=='value':","if True:"),
 'drop_product':source.replace("keys=('product','version','operator')","keys=('version','operator')"),
 'drop_source_checks':source.replace("result['solver_source_supported']=match(result['solver'],source)","result['solver_source_supported']=True").replace("result['support_source_supported']=match(result['support'],source)","result['support_source_supported']=True"),
 'decimal_versions':source.replace("all(a[k]==b[k] for k in keys)","all(((float('.'.join(map(str,a[k]))) if len(a[k])==2 else a[k])==(float('.'.join(map(str,b[k]))) if len(b[k])==2 else b[k])) if k=='version' else a[k]==b[k] for k in keys)")}
result=[]
for name,code in mutations.items():
 module=types.ModuleType('mutant');exec(compile(code,name,'exec'),module.__dict__)
 with patch.object(v,'compare',module.compare):
  output=io.StringIO();r=unittest.TextTestRunner(stream=output).run(unittest.TestSuite([VersionTests('test_near_misses'),VersionTests('test_agreement_is_not_enough')]))
 result.append({'mutation':name,'detected':not r.wasSuccessful(),'failures':len(r.failures),'errors':len(r.errors),'output':output.getvalue()})
print(json.dumps(result,indent=2));assert all(x['detected'] and not x['errors'] for x in result)
