import os
import re
import glob

components_dir = r"c:\Users\rlagu\OneDrive\바탕 화면\개발\APEX CARE\src\components"

replacements = [
    (r'(?<!dark:)\btext-white\b', 'text-black dark:text-white'),
    (r'(?<!dark:)\btext-slate-100\b', 'text-gray-900 dark:text-slate-100'),
    (r'(?<!dark:)\btext-slate-200\b', 'text-gray-800 dark:text-slate-200'),
    (r'(?<!dark:)\btext-slate-300\b', 'text-gray-700 dark:text-slate-300'),
    (r'(?<!dark:)\btext-slate-400\b', 'text-gray-500 dark:text-slate-400'),
    (r'(?<!dark:)\bbg-slate-950\b', 'bg-gray-100 dark:bg-slate-950'),
    (r'(?<!dark:)\bbg-slate-900\b', 'bg-white dark:bg-slate-900'),
    (r'(?<!dark:)\bbg-slate-800\b', 'bg-gray-50 dark:bg-slate-800'),
    (r'(?<!dark:)\bbg-slate-700\b', 'bg-gray-100 dark:bg-slate-700'),
    (r'(?<!dark:)\bborder-slate-900\b', 'border-black/10 dark:border-slate-900'),
    (r'(?<!dark:)\bborder-slate-800\b', 'border-black/10 dark:border-slate-800'),
    (r'(?<!dark:)\bborder-slate-700\b', 'border-black/10 dark:border-slate-700'),
    (r'(?<!dark:)\bborder-slate-600\b', 'border-black/20 dark:border-slate-600'),
]

for filepath in glob.glob(os.path.join(components_dir, "*.jsx")):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for pattern, repl in replacements:
        new_content = re.sub(pattern, repl, new_content)
        
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {os.path.basename(filepath)}")

print("Done.")
