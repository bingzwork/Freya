from app.core.logger import logger


class AgentBrain:

    def __init__(
        self,
        llm,
        tools,
    ):

        self.llm = llm
        self.tools = tools


    def analyze_project(self):

        result = self.tools.execute(
            "list_files"
        )

        if not result.success:

            return "Could not read project files."


        files = result.output[:100]


        file_list = "\n".join(
            files
        )


        prompt = f"""
You are Freya.

Analyze this software project.

Files:

{file_list}

Explain:
- project purpose
- important files
- possible improvements
"""


        return self.llm.ask(prompt)


    def solve(self, task):

        logger.info(
            f"Solving task: {task}"
        )


        prompt = f"""
You are Freya, an autonomous AI coding agent.

Task:
{task}

Give a detailed solution.
"""


        return self.llm.ask(prompt)