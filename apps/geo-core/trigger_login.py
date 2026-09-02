# 触发发布端登录(百家号 type=9),读取 SSE 状态直到登录成功/失败/超时
# 运行后会弹出 Chrome 窗口,请在窗口内登录百家号账号(5 分钟超时)
import sys
import time
import requests

PUB = "http://localhost:5409"


def trigger(platform_type: int, account_id: str):
    url = f"{PUB}/login?type={platform_type}&id={account_id}"
    print(f"触发登录: 平台type={platform_type} 账号={account_id}")
    print(">> 请在弹出的 Chrome 窗口中登录百家号(密码/扫码均可,5分钟超时)")
    last = None
    start = time.time()
    try:
        with requests.get(url, stream=True, timeout=320) as r:
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data:"):
                    msg = line[len("data:"):].strip()
                    if msg != last:
                        print("<<", msg)
                        last = msg
                        # 登录成功/失败即结束
                        if '"code": 200' in msg and "Cookie已保存" in msg:
                            pass
                        if "登录成功" in msg:
                            print("✅ 百家号登录成功,Cookie 已落盘")
                            return True
                        if '"code": 500' in msg or "失败" in msg or "超时" in msg:
                            print("❌ 登录失败")
                            return False
                if time.time() - start > 310:
                    print("⏰ 超时")
                    return False
    except Exception as e:
        print("请求异常:", e)
        return False
    return False


if __name__ == "__main__":
    acc = sys.argv[2] if len(sys.argv) > 2 else "my_baijiahao"
    ptype = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    ok = trigger(ptype, acc)
    sys.exit(0 if ok else 1)
