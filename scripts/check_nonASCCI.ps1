Get-ChildItem -Recurse -Include *.json,*.txt,*.py | ForEach-Object {
  try {
    $s = Get-Content $_.FullName -Raw -Encoding utf8
    if ($s -match '[^\u0000-\u007F]') { Write-Output "$($_.FullName) contains non-ASCII chars" }
  } catch {}
}
