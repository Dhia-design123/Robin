import subprocess
import tempfile
import os
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def register(mcp):
    @mcp.tool()
    def create_task_document(topic: str, task_type: str = "general") -> str:
        """
        Researches a topic (recipe, how-to, instructions, plan, etc.), writes full
        details to a text file, and opens it in Notepad. Returns a short 1-2 sentence
        summary to be spoken aloud, while the full details are in the opened file.

        task_type examples: 'recipe', 'how-to', 'plan', 'general'
        """
        try:
            # Step 1: Generate the full detailed content
            prompt = f"""Write complete, detailed {task_type} content for: {topic}

Include all necessary steps, ingredients, or details a person would need to
actually follow this without needing anything else. Format it clearly with
headers and numbered/bulleted steps where appropriate. Be thorough."""

            completion = _client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
            )
            full_content = completion.choices[0].message.content

            # Step 2: Write it to a text file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_topic = "".join(c if c.isalnum() or c in " -_" else "" for c in topic)[:50]
            filepath = os.path.join(
                tempfile.gettempdir(), f"Robin_{safe_topic}_{timestamp}.txt"
            )
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"{topic.upper()}\n{'=' * len(topic)}\n\n")
                f.write(full_content)

            # Step 3: Open it in Notepad
            subprocess.Popen(["notepad.exe", filepath])

            # Step 4: Generate a short spoken summary
            summary_prompt = f"""Summarize this in exactly 1-2 short spoken sentences,
as if telling someone what you just wrote down for them:

{full_content}"""
            summary_completion = _client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": summary_prompt}],
            )
            summary = summary_completion.choices[0].message.content

            return f"{summary} I've opened the full details in Notepad for you."

        except Exception as e:
            return f"I ran into an issue creating that document: {e}"