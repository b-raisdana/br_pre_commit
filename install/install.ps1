#!/usr/bin/env pwsh
echo "Python: $(Get-Command python | Select-Object -ExpandProperty Source)"
python br_pre_commit//install//install.py $args
