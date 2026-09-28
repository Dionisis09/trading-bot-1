import subprocess, shlex
variants = [f'DualTrendFuturesV5_v{i}' for i in range(1,7)]
splits = [('train','20210101-20240101',0.0005), ('validation','20240101-20260101',0.0005)]
for var in variants:
    for split_name, timerange, fee in splits:
        notes = f'phase=dual_v5_sweep;variant={var};split={split_name};fee={fee}'
        cmd = ['docker', 'compose', 'run', '--rm', 'freqtrade', 'backtesting', '-c', '/freqtrade/user_data/config.json', '-c', '/freqtrade/user_data/config-dual-futures-v2r-dry-run.json', '--userdir', '/freqtrade/user_data', '--strategy-path', '/freqtrade/user_data/strategies', '--timeframe', '4h', '--timerange', timerange, '--fee', str(fee), '-s', var, '--notes', notes]
        print('\nRUNNING:', ' '.join(cmd))
        subprocess.run(cmd)
