build:
	uv run nuitka --enable-plugin=pyside6 --output-dir=dist --remove-output -o dist/mcqsnap main.py

install: build
	install -Dm755 dist/mcqsnap ~/.local/bin/mcqsnap