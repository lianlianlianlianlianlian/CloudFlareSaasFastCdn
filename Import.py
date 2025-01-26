import zipfile
import os
import requests
import subprocess

# 配置参数
ping_file = "ping.txt"  # 存储成功ping通的IP地址的文件
zip_url = "https://zip.baipiao.eu.org/"  # 包含IP地址列表的zip文件的URL
ports = ["80", "443"]  # 需要筛选的端口号
selected_ip_prefixes = ["43", "124", "8", "47", "34", "35", "93", "129", "101", "149", "23"]  # 需要筛选的IP地址前缀

def download_and_extract():
    """
    下载并解压包含IP地址列表的zip文件，并将符合条件的IP地址合并到一个文件中。
    """
    # 第一步：下载zip文件
    response = requests.get(zip_url)
    zip_file_path = "download.zip"  # 下载的zip文件保存路径

    # 将下载的内容写入到本地文件
    with open(zip_file_path, "wb") as file:
        file.write(response.content)

    # 第二步：解压zip文件
    extracted_files_dir = "./extracted_files/"  # 解压后的文件存放目录
    os.makedirs(extracted_files_dir, exist_ok=True)  # 创建解压目录，如果目录已存在则忽略

    # 解压zip文件到指定目录
    with zipfile.ZipFile(zip_file_path, "r") as zip_ref:
        zip_ref.extractall(extracted_files_dir)

    # 第三步：将符合条件的文本文件合并为一个文件
    combined_file_path = "ips.txt"  # 合并后的IP地址文件路径

    # 打开合并文件，准备写入
    with open(combined_file_path, "w") as combined_file:
        # 遍历解压后的目录，找到所有符合条件的文本文件
        for root, dirs, files in os.walk(extracted_files_dir):
            for file in files:
                if file.endswith(".txt"):  # 只处理.txt文件
                    file_path = os.path.join(root, file)
                    for port in ports:
                        if f'-{port}.' in file:  # 如果文件名中包含指定的端口号
                            with open(file_path, "r") as txt_file:
                                combined_file.write(txt_file.read())  # 将文件内容写入合并文件

    print(f"IP地址已合并到文件: {combined_file_path}")
    return combined_file_path  # 返回合并后的文件路径

def classify_and_ping_ips(input_file, output_file):
    """
    从合并的IP地址文件中筛选出符合条件的IP地址，并对这些IP地址进行ping测试，
    将成功ping通的IP地址保存到输出文件中。
    """
    # 第四步：筛选IP地址
    selected_ips = []  # 用于存储符合条件的IP地址
    with open(input_file, "r") as file:
        for line in file:
            ip = line.strip()  # 去除每行的空白字符
            # 如果IP地址以指定的前缀开头，则将其加入筛选列表
            if any(ip.startswith(prefix) for prefix in selected_ip_prefixes):
                selected_ips.append(ip)

    # 第五步：对筛选出的IP地址进行ping测试，并将成功ping通的IP地址保存到输出文件中
    existing_ips = set()  # 用于存储已存在于输出文件中的IP地址
    if os.path.exists(output_file):  # 如果输出文件已存在，读取其中的IP地址
        with open(output_file, "r") as file:
            existing_ips = set(line.strip() for line in file)

    # 打开输出文件，准备追加写入
    with open(output_file, "a") as file:
        for ip in selected_ips:
            if ip not in existing_ips:  # 如果IP地址不在已存在的IP地址集合中
                try:
                    # 使用ping命令测试IP地址的可达性
                    result = subprocess.run(["ping", "-c", "1", "-W", "1", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if result.returncode == 0:  # 如果ping命令成功返回
                        file.write(f"{ip}\n")  # 将IP地址写入输出文件
                        print(f"已将 {ip} 添加到 {output_file}")
                except Exception as e:
                    print(f"ping {ip} 时出错: {e}")

    print(f"新的成功ping通的IP地址已添加到: {output_file}")

def main():
    """
    主函数：下载并解压IP地址文件，筛选并ping测试IP地址，将结果保存到指定文件中。
    """
    combined_file_path = download_and_extract()  # 下载并解压IP地址文件
    classify_and_ping_ips(combined_file_path, ping_file)  # 筛选并ping测试IP地址

if __name__ == "__main__":
    main()  # 执行主函数
