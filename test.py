import os
import subprocess
import json
import concurrent.futures
import threading
import time

# 配置参数
TEST_DOMAIN = "darklotus.cn"  # 测试的域名，用于curl测试，这是我自己的网站。开源之后请改为你自己的，避免因为我开启防火墙测试脚本失败。
PING_COUNT = 5  # ping测试时发送的包数
CURL_COUNT = 5  # curl测试的次数
CURL_TIMEOUT = 10  # curl测试的超时时间（秒）
MIN_PING_SUCCESS = 1  # 最小成功ping次数，达到此数即认为ping测试通过
MIN_CURL_SUCCESS = 1  # 最小成功curl次数，达到此数即认为curl测试通过
CLEAN_FAIL_IP = 5  # IP在JSON中达到此失败次数后将被删除
CHECK_HOST = "baidu.com"  # 用于检查网络连接的域名
CHECK_PING_COUNT = 1  # 检查网络连接时使用的ping包数
CHECK_TIMEOUT = 5  # 检查网络连接的超时时间（秒）
LOG_FAILED_IPS = True  # 是否记录失败的IP，True表示记录
PING_THRESHOLD = 200  # 最大可接受的ping时间（毫秒）

# 文件路径
IP_FILE = "ping.txt"
LOG_FILE = "ip_log.json"
BLACKLIST_FILE = "黑名单.txt"  # 新增黑名单文件路径

# 锁用于同步访问 JSON 文件
json_lock = threading.Lock()

def read_file(file_path):
    if not os.path.exists(file_path):
        print(f"文件 {file_path} 不存在，正在创建空文件。")
        open(file_path, 'a').close()
    with open(file_path, "r", encoding="utf-8") as file:
        lines = [line.strip() for line in file if line.strip()]
    unique_ips = list(set(lines))  # 去重
    write_file(file_path, unique_ips)  # 覆盖写入以避免重复
    return unique_ips

def write_file(file_path, content):
    with open(file_path, "w", encoding="utf-8") as file:
        file.write("\n".join(content) + "\n")

def check_network():
    try:
        subprocess.check_output(f"ping -c {CHECK_PING_COUNT} {CHECK_HOST}", shell=True, timeout=CHECK_TIMEOUT)
        return True
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False

# 新增函数：读取黑名单文件
def read_blacklist():
    if not os.path.exists(BLACKLIST_FILE):
        print(f"黑名单文件 {BLACKLIST_FILE} 不存在，返回空列表。")
        return []
    with open(BLACKLIST_FILE, "r", encoding="utf-8") as file:
        return [line.strip() for line in file if line.strip()]

def ping_ip(ip):
    if not check_network():
        raise Exception("网络连接不可用，停止测试。")
    try:
        output = subprocess.check_output(f"ping -c {PING_COUNT} {ip}", shell=True, text=True, timeout=5)
        success_count = 0
        total_time = 0
        for line in output.splitlines():
            if "time=" in line:
                ping_time = float(line.split('time=')[1].split(' ')[0])
                if ping_time > PING_THRESHOLD:
                    return None  # 返回None如果ping时间超过阈值，表示需要移除
                total_time += ping_time
                success_count += 1
            if success_count >= MIN_PING_SUCCESS:
                return total_time / success_count if total_time > 0 else None
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None

def test_ip_with_curl(ip):
    if not check_network():
        raise Exception("网络连接不可用，停止测试。")
    success_count = 0
    curl_times = []
    for _ in range(CURL_COUNT):
        start_time = time.time()
        cmd = f"curl --resolve {TEST_DOMAIN}:443:{ip} -I -s -m {CURL_TIMEOUT} -o /dev/null -w '%{{http_code}}\n%{{time_total}}' https://{TEST_DOMAIN}"
        try:
            output = subprocess.check_output(cmd, shell=True, text=True, timeout=CURL_TIMEOUT).splitlines()
            status_code = output[0].strip()
            if status_code == "200":
                success_count += 1
                curl_times.append(float(output[1]))
        except subprocess.TimeoutExpired:
            return "None", None
        except subprocess.CalledProcessError:
            return "None", None
        if success_count >= MIN_CURL_SUCCESS:
            # 计算平均CURL时间
            avg_time = sum(curl_times) / len(curl_times) if curl_times else None
            return "200", avg_time
    return "None", None

def log_ip_test(ip, delay, status_code, curl_time=None):
    with json_lock:
        try:
            with open(LOG_FILE, 'r') as file:
                data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}

        if ip not in data:
            data[ip] = {"delays": None, "curl_times": None, "success_count": 0, "fail_count": 0}
        
        if status_code == "200":
            data[ip]["delays"] = delay if delay is not None else None
            data[ip]["curl_times"] = curl_time if curl_time is not None else None
            data[ip]["success_count"] += 1
            data[ip]["fail_count"] = 0  # 重置失败计数，当测试通过时
            print(f"IP {ip} 测试成功 延迟: {delay if delay is not None else 'N/A'} ms 成功次数: {data[ip]['success_count']} CURL时间: {curl_time:.2f} 秒")
        else:
            data[ip]["delays"] = None
            data[ip]["curl_times"] = None
            data[ip]["fail_count"] += 1
            print(f"IP {ip} 测试失败 失败次数: {data[ip]['fail_count']}")

        try:
            with open(LOG_FILE, 'w') as file:
                json.dump(data, file, indent=4)
        except IOError:
            print(f"无法写入 {LOG_FILE}")

def remove_ip(ip):
    with json_lock:
        try:
            with open(LOG_FILE, 'r') as file:
                data = json.load(file)
            if ip in data:
                del data[ip]
                with open(LOG_FILE, 'w') as file:
                    json.dump(data, file, indent=4)
            
            # 从ping.txt中删除IP
            with open(IP_FILE, 'r', encoding='utf-8') as file:
                ips = [line.strip() for line in file if line.strip() and line.strip() != ip]
            write_file(IP_FILE, ips)
            
            print(f"已删除IP: {ip} 因为ping超时超过阈值或在黑名单中")
        except (FileNotFoundError, json.JSONDecodeError):
            print("无法删除IP或处理日志文件。")

def process_ip(ip):
    try:
        delay = ping_ip(ip)
        if delay is None:  # 如果ping失败或超过阈值，直接删除IP
            remove_ip(ip)
            return None
        
        status_code, curl_time = test_ip_with_curl(ip)
        log_ip_test(ip, delay, status_code, curl_time)
        
        if status_code == "200" and delay is not None:
            return ip
    except Exception as e:
        print(f"在处理IP {ip} 时发生错误: {e}")
        if "网络连接不可用" in str(e):
            raise  
        return None

def clean_log_and_ping():
    with json_lock:
        try:
            # 读取黑名单
            blacklist_ips = read_blacklist()

            with open(LOG_FILE, 'r') as file:
                data = json.load(file)
            
            # 获取当前ping.txt中的所有IP
            with open(IP_FILE, 'r', encoding='utf-8') as file:
                current_ips = set([line.strip() for line in file if line.strip()])
            
            to_remove = []
            for ip in data.keys():
                if ip not in current_ips or data[ip]["fail_count"] >= CLEAN_FAIL_IP or ip in blacklist_ips:
                    to_remove.append(ip)
                    reason = "不在ping.txt中" if ip not in current_ips else "失败次数: " + str(data[ip]['fail_count']) if data[ip]["fail_count"] >= CLEAN_FAIL_IP else "在黑名单中"
                    print(f"准备删除 IP {ip}，原因: {reason}")  # 记录被删除的 IP

            for ip in to_remove:
                del data[ip]
            
            with open(LOG_FILE, 'w') as file:
                json.dump(data, file, indent=4)
            
            if to_remove:
                print(f"已清理 {LOG_FILE}，删除了 {len(to_remove)} 个IP记录。")
                
                # 同步更新 ping.txt
                with open(IP_FILE, 'r', encoding='utf-8') as file:
                    current_ips = [line.strip() for line in file if line.strip()]
                updated_ips = [ip for ip in current_ips if ip not in to_remove]
                write_file(IP_FILE, updated_ips)
                
                print(f"已从 {IP_FILE} 中删除了 {len(to_remove)} 个IP。")
                print(f"已确保 {IP_FILE} 与 {LOG_FILE} 同步。")
            else:
                print(f"没有需要清理的IP记录，{LOG_FILE} 中未删除任何IP。")
        except (FileNotFoundError, json.JSONDecodeError):
            print("无法清理或处理日志文件。")

def compare_ip_lists():
    with open(IP_FILE, 'r', encoding='utf-8') as file:
        txt_ips = set([line.strip() for line in file if line.strip()])
    
    with open(LOG_FILE, 'r') as file:
        json_data = json.load(file)
    
    json_ips = set(json_data.keys())

    if txt_ips == json_ips:
        print("ping.txt 和 ip_log.json 中的IP列表一致。")
    else:
        print("警告: ping.txt 和 ip_log.json 中的IP列表不一致！")
        print(f"ping.txt: {txt_ips}")
        print(f"ip_log.json: {json_ips}")

def main():
    print("# 检查IP - 开始")

    # 读取并去重 IP 列表
    original_ips = read_file(IP_FILE)

    if not original_ips:
        print(f"{IP_FILE} 文件未提供有效内容，脚本退出。")
        return

    if not check_network():
        print("网络连接不可用，停止测试。")
        return

    # 新增逻辑：检查并初始化 JSON 文件
    if not os.path.exists(LOG_FILE):
        print(f"{LOG_FILE} 不存在，初始化日志文件。")
        write_file(LOG_FILE, {})
    else:
        try:
            with open(LOG_FILE, 'r') as file:
                json.load(file)
        except json.JSONDecodeError:
            print(f"{LOG_FILE} 文件格式错误，初始化日志文件。")
            write_file(LOG_FILE, {})

    # 测试阶段
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ip = {executor.submit(process_ip, ip): ip for ip in original_ips}
        for future in concurrent.futures.as_completed(future_to_ip):
            try:
                result = future.result()
                if result:
                    # 现在只打印测试成功的详细信息
                    pass  # 这里不需要额外的日志
            except Exception as e:
                if "网络连接不可用" in str(e):
                    print("网络连接不可用，停止测试。")
                    for f in future_to_ip:
                        f.cancel()
                    break
                else:
                    print(f"处理IP时遇到错误: {e}")

    # 清理阶段
    print("\n# 开始清理过程")
    clean_log_and_ping()

    # 比对 txt 和 json 文件中的 IP 是否一致
    compare_ip_lists()

    # 最后查询并打印ping.txt中的IP数量
    # 直接读取文件内容，因为清理已经完成且文件已更新
    with open(IP_FILE, 'r', encoding='utf-8') as file:
        final_ips = [line.strip() for line in file if line.strip()]
    print(f"\nping.txt 当前包含 {len(final_ips)} 个IP。")

    print("# IP检查完成")

if __name__ == "__main__":
    main()
