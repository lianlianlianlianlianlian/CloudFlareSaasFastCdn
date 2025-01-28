import aiohttp
import asyncio
import json
import ipaddress

# Cloudflare API配置
API_TOKEN = '你的CloudFlare token'
ZONE_ID = '你的域名空间ID'
RECORD_NAME = 'xxx.com'# 你想要ddns的域名
RECORD_TYPE = 'A' # A记录
MAX_RECORDS = 10 # 最多只能添加10条解析 超过会删除多余的 
API_BASE_URL = 'https://api.cloudflare.com/client/v4'
LOG_FILE = "ip_log.json"

# 新增黑名单文件路径
BLACKLIST_FILE_PATH = '黑名单.txt'

HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json'
}

# 从 ip_log.json 获取最佳IP
def get_best_ips(num_ips):
    try:
        with open(LOG_FILE, 'r') as file:
            data = json.load(file)
        
        # 读取黑名单
        blacklist_ips = load_blacklist_ips()
        
        # 排序以获取最佳的IP，但只考虑失败次数为0的IP
        sorted_ips = sorted(
            [(ip, info) for ip, info in data.items() if not is_blacklisted(ip, blacklist_ips) and info.get('fail_count', 0) == 0],
            key=lambda x: (
                x[1].get('delays', float('inf')) if x[1].get('delays') is not None else float('inf'),  
                -x[1].get('success_count', 0), 
                x[1].get('curl_times', float('inf')) if x[1].get('curl_times') is not None else float('inf')  
            )
        )
        
        # 返回前num_ips个最佳IP
        return [ip for ip, _ in sorted_ips[:num_ips]]
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"无法读取或解析 {LOG_FILE}")
        return []

# 加载黑名单IP
def load_blacklist_ips():
    try:
        with open(BLACKLIST_FILE_PATH, 'r') as file:
            lines = file.readlines()
            blacklist = []
            for line in lines:
                line = line.strip()
                if '/' in line:  # 处理IP段
                    ip, mask = line.split('/')
                    blacklist.append((ip, int(mask)))
                else:
                    blacklist.append(line)
            return blacklist
    except FileNotFoundError:
        print(f"黑名单文件 {BLACKLIST_FILE_PATH} 不存在，将忽略黑名单过滤。")
        return []

# 检查IP是否在黑名单中
def is_blacklisted(ip, blacklist):
    for item in blacklist:
        if isinstance(item, tuple):  # IP段
            ip_part, mask = item
            if ipaddress.IPv4Address(ip) in ipaddress.IPv4Network(f"{ip_part}/{mask}"):
                return True
        elif ip == item:  # 完整IP
            return True
    return False

# 获取当前 Cloudflare 中的 DNS 记录
async def get_existing_records():
    url = f'{API_BASE_URL}/zones/{ZONE_ID}/dns_records'
    records = {}
    page = 1

    async with aiohttp.ClientSession() as session:
        while True:
            params = {'type': RECORD_TYPE, 'name': RECORD_NAME, 'per_page': 100, 'page': page}
            async with session.get(url, headers=HEADERS, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('success'):
                        for record in data.get('result', []):
                            records[record['content']] = record['id']
                        if data.get('result_info', {}).get('total_pages', 1) > page:
                            page += 1
                        else:
                            break
                    else:
                        print('查询DNS记录失败:', data.get('errors'))
                        break
                else:
                    print('查询DNS记录失败:', await response.text())
                    break

    return records

# 删除 DNS 记录
async def delete_ddns_record(session, record_id, existing_records):
    url = f'{API_BASE_URL}/zones/{ZONE_ID}/dns_records/{record_id}'
    async with session.delete(url, headers=HEADERS) as response:
        if response.status == 200:
            data = await response.json()
            if data.get('success'):
                for ip, id in existing_records.items():
                    if id == record_id:
                        print(f'删除DNS记录成功: {RECORD_NAME} -> {ip}')
                        break
            else:
                print('删除DNS记录失败:', data.get('errors'))
        else:
            print('删除DNS记录失败:', await response.text())

# 创建 DNS 记录
async def create_ddns_record(session, ip):
    blacklist_ips = load_blacklist_ips()  # 加载黑名单
    if is_blacklisted(ip, blacklist_ips):
        print(f'跳过创建DNS记录，因为IP {ip} 在黑名单中')
        return None
    
    url = f'{API_BASE_URL}/zones/{ZONE_ID}/dns_records'
    data = {
        'type': RECORD_TYPE,
        'name': RECORD_NAME,
        'content': ip,
        'ttl': 1,
        'proxied': False
    }
    async with session.post(url, headers=HEADERS, json=data) as response:
        if response.status == 200:
            data = await response.json()
            if data.get('success'):
                print(f'创建DNS记录成功: {RECORD_NAME} -> {ip}')
                return data.get('result', {}).get('id')
            else:
                print(f'创建DNS记录失败: {RECORD_NAME} -> {ip}', data.get('errors'))
        else:
            print(f'创建DNS记录失败: {RECORD_NAME} -> {ip}', await response.text())
    return None

# 更新 DNS 记录
async def update_ddns_records():
    existing_records = await get_existing_records()
    best_ips = get_best_ips(MAX_RECORDS)

    async with aiohttp.ClientSession() as session:
        # 删除不在最佳IP列表内的任何现有记录
        to_delete = [ip for ip in existing_records if ip not in best_ips]
        delete_tasks = [delete_ddns_record(session, existing_records[ip], existing_records) for ip in to_delete]
        if delete_tasks:
            await asyncio.gather(*delete_tasks)

        # 重新获取现有记录，因为删除任务已经完成
        existing_records = await get_existing_records()
        
        # 添加缺少的最佳IP
        for ip in best_ips:
            if ip not in existing_records and len(existing_records) < MAX_RECORDS:
                record_id = await create_ddns_record(session, ip)
                if record_id:
                    existing_records[ip] = record_id

    # 确保解析的IP始终在json里，且符合条件
    updated_records = await get_existing_records()
    print(f"更新后的DNS记录数量: {len(updated_records)}")

# 主函数
async def main():
    print(f"从 {LOG_FILE} 获取最佳IP")
    
    existing_records = await get_existing_records()
    print(f"当前解析的IP数量: {len(existing_records)}")

    await update_ddns_records()

    # 末尾日志
    print("# IP检查完成")

if __name__ == '__main__':
    asyncio.run(main())
