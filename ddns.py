import json
import requests
import random
import time
import subprocess

# 配置参数
DNSpod_API_ID = "123456" # dnspod的API ID
DNSpod_API_TOKEN = "9c774f1cc26461eea18228e0c5840f17"# dnspod的API Token
DNSpod_DOMAIN = "darklotus.cn"# 主域名
DNSpod_SUB_DOMAIN = "fastcdn"  # 子域名
DNSpod_RECORD_TYPE = "A"  # 记录类型
DNSpod_RECORD_LINE = "默认"  # 记录线路
API_ENDPOINT = "https://dnsapi.cn"
TEST_DOMAIN = "darklotus.cn"  # 测试解析的域名，不要用我的，改为你自己。
MAX_A_RECORDS = 2  # 最多允许的 A 记录数
MAX_CNAME_RECORDS = 1  # 最多允许的 CNAME 记录数
REQUEST_TIMEOUT = 30  # 请求超时时间
PING_COUNT = 5  # Ping测试的次数
MAX_PING_RETRIES = 5  # 最大ping测试重试次数
CURL_TIMEOUT = 2  # curl请求超时时间，秒

# 文件路径
LOG_FILE = "ip_log.json"

def api_request(api_name, data):
    url = f"{API_ENDPOINT}/{api_name}"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "DNSPod-DDNS/1.0.0 (darklotus.cn)"
    }
    data.update({"login_token": f"{DNSpod_API_ID},{DNSpod_API_TOKEN}", "format": "json"})
    attempt = 0
    max_retries = 5
    while attempt < max_retries:
        try:
            response = requests.post(url, data=data, headers=headers, timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                print(f"请求失败，状态码：{response.status_code}")
                return None
            return response.json()
        except requests.Timeout:
            print(f"请求超时：{url}，尝试 {attempt + 1}/{max_retries}")
        except requests.RequestException as e:
            print(f"请求发生错误：{e}，尝试 {attempt + 1}/{max_retries}")
        attempt += 1
        time.sleep(5 * (2 ** attempt) + random.uniform(0, 3))  # 指数退避
    return None

def get_current_records():
    attempt = 0
    max_retries = 5
    while attempt < max_retries:
        print(f"# 获取DNS记录 - 正在获取子域名 {DNSpod_SUB_DOMAIN}.{DNSpod_DOMAIN} 的解析记录...（尝试 {attempt + 1}/{max_retries}）")
        data = {
            "domain": DNSpod_DOMAIN,
            "sub_domain": DNSpod_SUB_DOMAIN,
        }
        response = api_request("Record.List", data)
        if response and response.get("status", {}).get("code") == "1":
            return response.get("records", [])
        elif response and response.get("status", {}).get("code") == "10":  # 记录列表为空
            print("# 获取DNS记录 - 记录列表为空，将使用日志中的IP进行更新")
            return []
        else:
            print(f"获取解析记录失败：{response}")
        attempt += 1
        time.sleep(5 + random.uniform(0, 3))  # 等待并增加随机延迟
    print("# 获取DNS记录 - 无法获取DNS记录")
    return []

def update_record(record_id, record_type, value, line="默认"):
    attempt = 0
    max_retries = 5
    while attempt < max_retries:
        data = {
            "domain": DNSpod_DOMAIN,
            "record_id": record_id,
            "sub_domain": DNSpod_SUB_DOMAIN,
            "record_type": record_type,
            "record_line": line,
            "value": value
        }
        response = api_request("Record.Modify", data)
        if response and response.get("status", {}).get("code") == "1":
            return True
        elif response and response.get("status", {}).get("code") == "104":
            return True  # 如果记录已经存在，无需再次添加
        else:
            print(f"更新记录失败：{response}")
        attempt += 1
        time.sleep(5 * (2 ** attempt) + random.uniform(0, 3))  # 指数退避
    return False

def create_record(record_type, value, line="默认"):
    attempt = 0
    max_retries = 5
    while attempt < max_retries:
        data = {
            "domain": DNSpod_DOMAIN,
            "sub_domain": DNSpod_SUB_DOMAIN,
            "record_type": record_type,
            "record_line": line,
            "value": value
        }
        response = api_request("Record.Create", data)
        if response and response.get("status", {}).get("code") == "1":
            return True
        print(f"创建记录失败，尝试 {attempt + 1}/{max_retries}, 错误详情: {response}")
        attempt += 1
        time.sleep(5 * (2 ** attempt) + random.uniform(0, 3))  # 指数退避
    return False

def delete_record(record_id):
    attempt = 0
    max_retries = 5
    while attempt < max_retries:
        data = {
            "domain": DNSpod_DOMAIN,
            "record_id": record_id
        }
        response = api_request("Record.Remove", data)
        if response and response.get("status", {}).get("code") == "1":
            return True
        print(f"删除记录失败，尝试 {attempt + 1}/{max_retries}, 错误详情: {response}")
        attempt += 1
        time.sleep(5 * (2 ** attempt) + random.uniform(0, 3))  # 指数退避
    return False

def test_ip_with_curl(ip):
    cmd = f"curl --resolve {TEST_DOMAIN}:443:{ip} -I -s -m {CURL_TIMEOUT} -o /dev/null -w '%{{http_code}}\n%{{time_total}}' https://{TEST_DOMAIN}"
    try:
        output = subprocess.check_output(cmd, shell=True, text=True).splitlines()
        status_code = output[0].strip()
        if status_code == "200":
            return status_code, float(output[1])  # 返回状态码和时间
        else:
            return status_code, None
    except subprocess.CalledProcessError as e:
        if e.returncode == 28:
            print(f"CURL 测试 {ip} 操作超时")
        else:
            print(f"CURL 测试 {ip} 失败，curl 退出码：{e.returncode}")
        return "None", None

def select_best_ip_from_log(current_ips):
    try:
        with open(LOG_FILE, 'r') as file:
            log_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print("# 从日志中没有找到符合条件的IP。")
        return None

    valid_ips = []
    for ip, stats in log_data.items():
        if ip not in current_ips:
            # 如果没有 fail_count，则忽略这个条件
            fail_count = stats.get('fail_count', 0)
            if fail_count == 0 or 'fail_count' not in stats:
                delay = stats.get('delays', float('inf'))
                curl_time = stats.get('curl_times', float('inf'))
                success_count = stats.get('success_count', 0)
                valid_ips.append((ip, success_count, delay, curl_time))

    if not valid_ips:
        print("# 从日志中没有找到符合条件的新IP。")
        return None

    # 排序：按成功次数降序、延迟升序、CURL时间升序
    valid_ips.sort(key=lambda x: (-x[1], x[2], x[3]))  
    return valid_ips[0][0]  # 返回最佳 IP

def update_success_count(ip):
    try:
        with open(LOG_FILE, 'r') as file:
            log_data = json.load(file)
        if ip in log_data:
            log_data[ip]['success_count'] = log_data[ip].get('success_count', 0) + 1
            with open(LOG_FILE, 'w') as file:
                json.dump(log_data, file, indent=4)
            print(f"# IP {ip} 的成功次数增加了。")
        else:
            print(f"# IP {ip} 不在日志中，不能增加成功次数。")
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"# 无法增加 {ip} 的成功次数，因为无法读取或写入日志文件。")

def main():
    print("# 获取DNS记录 - 开始")
    records = get_current_records()
    
    if not records:
        # 如果没有DNS记录，从日志中选择符合条件的IP
        print("# 从日志中选择IP进行DNS记录更新")
        best_ip = select_best_ip_from_log([])
        if best_ip:
            # 添加新IP前进行测试
            status_code, _ = test_ip_with_curl(best_ip)
            if status_code == "200":
                if create_record('A', best_ip):
                    print(f"# 从日志中添加新IP记录：{best_ip}")
                    update_success_count(best_ip)
                else:
                    print(f"# 从日志中选出新IP {best_ip} 但添加失败。")
            else:
                print(f"# 从日志中选出的IP {best_ip} 测试不符合条件，状态码：{status_code}")
        else:
            print("# 从日志中没有找到合适的IP来添加新记录。")
    else:
        print("# 测试现有IP - 开始")
        current_a_ips = [record for record in records if record['type'] == 'A' and record['line'] == "默认"]
        valid_ips = []

        for record in current_a_ips:
            ip = record['value']
            status_code, curl_time = test_ip_with_curl(ip)
            print(f"# IP {ip} 的成功次数增加了。")
            print(f"返回的状态码：{status_code} {('符合条件' if status_code == '200' else '不符合条件')}")
            if status_code == "200":
                valid_ips.append(ip)
                update_success_count(ip)
            else:
                if delete_record(record['id']):
                    print(f"# 删除不符合条件的IP - 删除了不符合条件的IP {ip}")
                else:
                    print(f"# 删除不符合条件的IP - 删除记录 {record['id']} 失败。")

        print(f"# 测试现有IP - 当前有 {len(valid_ips)} 个符合条件的IP：{valid_ips}")

        # 如果有效IP数少于MAX_A_RECORDS，则从日志中补充
        while len(valid_ips) < MAX_A_RECORDS:
            best_ip = select_best_ip_from_log(valid_ips)
            if not best_ip:
                print(f"# 填充A记录 - 没有更多符合条件的IP来填充到 {MAX_A_RECORDS} 个A记录。")
                break
            status_code, _ = test_ip_with_curl(best_ip)
            if status_code == "200":
                if create_record('A', best_ip):
                    print(f"# 填充A记录 - 从日志中选出的IP {best_ip}")
                    print(f"# 填充A记录 - 返回的状态码：{status_code} 符合条件")
                    print(f"# 填充A记录 - 成功添加新IP：{best_ip}，当前A记录数：{len(valid_ips) + 1}")
                    valid_ips.append(best_ip)
                    update_success_count(best_ip)
                else:
                    print(f"# 填充A记录 - 添加记录 {best_ip} 失败。")

        # 检查是否可以用更好的IP替换现有的IP
        if valid_ips:
            try:
                with open(LOG_FILE, 'r') as file:
                    log_data = json.load(file)
                best_ip = select_best_ip_from_log(valid_ips)
                if best_ip and best_ip not in valid_ips:
                    # 找到最差的IP来替换
                    replace_ip = max(valid_ips, key=lambda x: (log_data.get(x, {'delays': float('inf')})['delays'], 
                                                               log_data.get(x, {'curl_times': float('inf')})['curl_times'], 
                                                               -log_data.get(x, {'success_count': 0})['success_count']))
                    
                    # 获取新IP和要替换的旧IP的详细信息进行对比
                    best_ip_info = log_data.get(best_ip, {})
                    replace_ip_info = log_data.get(replace_ip, {})
                    
                    print(f"# 查询是更优IP - 从日志里查询到了IP {best_ip} 延迟 {'%.2f' % best_ip_info.get('delays', float('inf'))} ms, 最短CURL时间 {'%.2f' % best_ip_info.get('curl_times', float('inf'))} s, 成功次数 {best_ip_info.get('success_count', 0)}")
                    print(f"# 对比 {replace_ip}的延迟 {'%.2f' % replace_ip_info.get('delays', float('inf'))} ms, 最短CURL时间 {'%.2f' % replace_ip_info.get('curl_times', float('inf'))} s 和成功次数 {replace_ip_info.get('success_count', 0)}")
                    
                    # 检查新IP是否在所有方面都更好
                    if (best_ip_info.get('success_count', 0) > replace_ip_info.get('success_count', 0) or
                        (best_ip_info.get('success_count', 0) == replace_ip_info.get('success_count', 0) and
                         best_ip_info.get('delays', float('inf')) < replace_ip_info.get('delays', float('inf')) and
                         best_ip_info.get('curl_times', float('inf')) < replace_ip_info.get('curl_times', float('inf')))):
                        for record in records:
                            if record['type'] == 'A' and record['value'] == replace_ip and record['line'] == "默认":
                                if update_record(record['id'], 'A', best_ip):
                                    print(f"# 更新DNS记录 - 成功更新 IP：{best_ip}，替换了 {replace_ip}")
                                else:
                                    print(f"# 更新DNS记录 - 更新记录 {record['id']} 失败。")
                                break
                    else:
                        print("# 更新记录 - 当前IP已经是最佳，不需要更新。")
                else:
                    print("# 更新记录 - 无法找到更好的IP进行更新。")
            except (FileNotFoundError, json.JSONDecodeError):
                print("# 更新记录 - 无法读取日志文件，跳过更新。")

    print("# DDNS更新完成")

if __name__ == "__main__":
    main()
