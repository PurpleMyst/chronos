$requirements = & py -m poetry run py -m pip freeze
[IO.File]::WriteAllLines("requirements.txt", $requirements)
