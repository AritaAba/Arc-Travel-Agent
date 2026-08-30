import os
import yaml
from typing import Dict, List, Optional

class SkillLoader:
    def __init__(self, skills_dir: str = ".claude/skills"):
        current_file_path = os.path.abspath(__file__)
        project_root = os.path.dirname(os.path.dirname(current_file_path))
        self.skills_dir = os.path.join(project_root, skills_dir)
        self.skills: Dict[str, Dict] = {}

    def load_skills(self) -> Dict[str, Dict]:
        if not os.path.exists(self.skills_dir):
            print(f"Warning: Skills directory {self.skills_dir} not found.")
            return {}

        for skill_name in os.listdir(self.skills_dir):
            skill_path = os.path.join(self.skills_dir, skill_name)
            if os.path.isdir(skill_path):
                md_file = os.path.join(skill_path, "SKILL.md")
                if os.path.exists(md_file):
                    skill_info = self._parse_skill_md(md_file)
                    if skill_info:
                        self.skills[skill_info.get("name", skill_name)] = skill_info

        return self.skills

    def _parse_skill_md(self, file_path: str) -> Optional[Dict]:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()


            if content.startswith('---'):
                end_idx = content.find('---', 3)
                if end_idx != -1:
                    yaml_content = content[3:end_idx]
                    try:
                        data = yaml.safe_load(yaml_content)
                        return data
                    except yaml.YAMLError as e:
                        print(f"Error parsing YAML in {file_path}: {e}")
            return None
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return None

    def get_skill_prompt(self, skill_mapping: Optional[Dict[str, str]] = None) -> str:
        if not self.skills:
            self.load_skills()

        prompt_lines = []
        index = 1


        sorted_skills = sorted(self.skills.items())

        for name, info in sorted_skills:
            display_name = name
            if skill_mapping and name in skill_mapping:
                display_name = skill_mapping[name]
            elif skill_mapping:

                pass

            desc = info.get("description", "").replace("\n", " ")
            prompt_lines.append(f"{index}. {display_name} - {desc}")
            index += 1

        return "\n\n".join(prompt_lines)

    def get_skill_content(self, skill_name: str) -> Optional[str]:
        if not self.skills:
            self.load_skills()

        target_path = None


        test_dir_path = os.path.join(self.skills_dir, skill_name, "SKILL.md")
        if os.path.exists(test_dir_path):
            target_path = test_dir_path


        if not target_path:
            for dirname in os.listdir(self.skills_dir):
                skill_dir = os.path.join(self.skills_dir, dirname)
                if not os.path.isdir(skill_dir):
                    continue

                md_path = os.path.join(skill_dir, "SKILL.md")
                if os.path.exists(md_path):

                    info = self._parse_skill_md(md_path)
                    if info and info.get("name") == skill_name:
                        target_path = md_path
                        break

        if not target_path:
            return None

        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                content = f.read()


            if content.startswith('---'):
                end_idx = content.find('---', 3)
                if end_idx != -1:
                    content = content[end_idx+3:].strip()
            return content
        except Exception as e:
            print(f"Error reading skill content {target_path}: {e}")
            return None
