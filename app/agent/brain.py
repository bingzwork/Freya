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


        prompt = f"""Analyze this software project and describe:
- project purpose
- important files and their roles
- a few concrete, high-value improvements

Files:

{file_list}
"""


        return self.llm.ask(prompt)


    def solve(self, task):

        logger.info(
            f"Solving task: {task}"
        )


        prompt = f"""Solve the following task with a focused, detailed solution. Include each step the engineer should take and the smallest change that solves it.

Task:
{task}
"""


        return self.llm.ask(prompt)