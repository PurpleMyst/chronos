# Get the list of requirements, excluding the current project itself if present
$requirements = (py -m poetry run py -m pip freeze).Split([Environment]::NewLine) | `
    Where-Object { !$_.StartsWith("-e git+") }


# Write it to requirements.txt
[IO.File]::WriteAllLines("requirements.txt", $requirements)
