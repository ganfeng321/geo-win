import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from publisher_client import PublisherClient
p = PublisherClient()
stats = p.get_platform_stats()
print("stats:", stats)
for ps in stats.get("data",{}).get("platform_stats",[]):
    plat = ps.get("platform")
    valid = ps.get("valid")
    code = 9
    print(f"  plat={plat} type={type(plat)} valid={valid} code={code} eq={plat==code}")
print("_valid_accounts result:", p._valid_accounts("baijiahao"))
