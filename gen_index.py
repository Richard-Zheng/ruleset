import os
import html

# 設定目標資料夾路徑
TARGET_DIR = './gh-pages'

def generate_indices(base_dir):
    for root, dirs, files in os.walk(base_dir):
        # 取得目前資料夾相對於 TARGET_DIR 的相對路徑（用於標題顯示）
        rel_path = os.path.relpath(root, base_dir)
        display_title = "Index of /" if rel_path == "." else f"Index of /{rel_path}"
        
        index_path = os.path.join(root, 'index.html')
        
        with open(index_path, 'w', encoding='utf-8') as f:
            # 寫入 HTML 標頭與樣式
            f.write(f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(display_title)}</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; line-height: 1.6; }}
        h1 {{ border-bottom: 1px solid #ccc; padding-bottom: 10px; }}
        ul {{ list-style-type: none; padding-left: 0; }}
        li {{ padding: 5px 0; }}
        a {{ text-decoration: none; color: #0366d6; }}
        a:hover {{ text-decoration: underline; }}
        .dir::before {{ content: "📁 "; }}
        .file::before {{ content: "📄 "; }}
        .parent::before {{ content: "⬆️ "; }}
    </style>
</head>
<body>
    <h1>{html.escape(display_title)}</h1>
    <ul>
''')
            
            # 如果不是根目錄，加入「回到上一層」的連結
            if root != base_dir:
                f.write('        <li class="parent"><a href="../">Parent Directory</a></li>\n')
            
            # 排序目錄與檔案，讓顯示更整齊
            dirs.sort()
            files.sort()
            
            # 寫入子目錄連結
            for d in dirs:
                # 網頁路徑目錄末尾加上 /
                dir_link = f"{html.escape(d)}/"
                f.write(f'        <li class="dir"><a href="{dir_link}">{html.escape(d)}/</a></li>\n')
                
            # 寫入檔案連結
            for file in files:
                # 忽略剛生成的 index.html 本身
                if file.lower() == 'index.html':
                    continue
                file_link = html.escape(file)
                f.write(f'        <li class="file"><a href="{file_link}">{html.escape(file)}</a></li>\n')
                
            # 寫入 HTML 結尾
            f.write('''    </ul>
</body>
</html>
''')
            print(f"Generated: {index_path}")

if __name__ == '__main__':
    if os.path.exists(TARGET_DIR):
        generate_indices(TARGET_DIR)
        print("✨ 所有 index.html 遞迴生成完畢！")
    else:
        print(f"❌ 找不到目標資料夾：{TARGET_DIR}，請確認路徑是否正確。")
