from pathlib import Path


class FileLocator:

    def __init__(self, symbol_index):
        self.symbol_index = symbol_index

    def locate(self, query):

        query = query.lower()

        scored = []

        # ---------- Symbol matches ----------

        for file, symbols in self.symbol_index.symbols.items():

            score = 0

            best = None

            for symbol in symbols:

                name = symbol["name"].lower()

                if name == query:

                    score = 100

                    best = symbol

                    break

                elif query in name:

                    score = max(score, 80)

                    best = symbol

            if best:

                scored.append(
                    (
                        score,
                        {
                            "file": file,
                            **best,
                        },
                    )
                )

        # ---------- File matches ----------

        for file in self.symbol_index.files:

            stem = Path(file).stem.lower()

            filename = Path(file).name.lower()

            score = 0

            if filename == query:

                score = 95

            elif stem == query:

                score = 90

            elif query in filename:

                score = 70

            if score:

                scored.append(
                    (
                        score,
                        {
                            "file": file,
                            "type": "file",
                            "name": filename,
                            "line": 1,
                        },
                    )
                )

        scored.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        return [item for _, item in scored]

    def best_match(self, query):

        matches = self.locate(query)

        if not matches:
            return None

        return matches[0]

    def read(self, query):

        match = self.best_match(query)

        if match is None:
            return None

        return {
            "file": match["file"],
            "content": self.symbol_index.get_file(
                match["file"]
            ),
        }