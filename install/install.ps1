#!/usr/bin/env pwsh
echo "Python: $(Get-Command python | Select-Object -ExpandProperty Source)"
python (& $PSScriptRoot)/install.py $args
