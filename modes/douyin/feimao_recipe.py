"""飞猫(听雪)抖音通道的 ffmpeg 配方。

这个通道的配方原先拆成两个数据文件——`filter_complex.txt` 与 `feimao_ffargs.json`
——由 `scripts/build_protected.ps1` 用 `--include-data-files` 白名单明文进包。
那等于把通道算法（水印摆放、动画曲线、调色与混音参数）直接交给任何解压发布包的人。

现在改成模块常量，由 `--include-package=modes` 编译进启动器：发布包里没有任何可读副本。
请不要把它挪回数据文件。

`FILTER_GRAPH` 是抓取所得的产物，必须逐字保持原样：单行、无换行，含 12 个 U+1F431
（`drawtext` 的猫头水印）。`tests/test_feimao_yanjingshe_channels.py` 钉死了长度和水印
数量，任何编码损坏都会立刻报错，而不是悄悄改变出片结果。
"""


FILTER_GRAPH = "[0:v]fps=30,scale=w='if(gte(iw\\,ih)\\,1024\\,576)':h='if(gte(iw\\,ih)\\,576\\,1024)':flags=lanczos,setsar=1,format=yuv420p,split=2[main_src][cover_src];[main_src]setpts=PTS*0.995322,split=5[main_blend][main_ref_grid][main_ref_mask][main_ref_top][main_bg];[cover_src]trim=start_frame=0:end_frame=1,loop=loop=-1:size=1:start=0,setpts=N/(30*TB),scale=370:220:flags=lanczos,format=yuv420p,split=4[c0][c1][c2][c3];[c0]rotate='0.0391*sin(2*PI*0.557*t-0.1203)':ow=iw:oh=ih:fillcolor=black,crop=342:192:(iw-342)/2:(ih-192)/2,hue=h='8*sin(2*PI*t*0.20)':s=1.15[i0];[c1]rotate='0.0365*sin(2*PI*0.815*t-0.1747)':ow=iw:oh=ih:fillcolor=black,crop=342:192:(iw-342)/2:(ih-192)/2,hue=h='28+12*sin(2*PI*t*0.17)':s=1.20[i1];[c2]rotate='0.0520*sin(2*PI*0.419*t-0.0920)':ow=iw:oh=ih:fillcolor=black,crop=342:192:(iw-342)/2:(ih-192)/2,hue=h='-22+10*sin(2*PI*t*0.13)':s=1.20[i2];[c3]rotate='0.0372*sin(2*PI*0.933*t-0.2006)':ow=iw:oh=ih:fillcolor=black,crop=342:192:(iw-342)/2:(ih-192)/2,hue=h='14+10*sin(2*PI*t*0.11)':s=1.18[i3];testsrc=size=342x192:rate=30,format=yuv420p,split=5[s0][s1][s2][s3][s4];[s0]eq=brightness=0.03:saturation=0.90,boxblur=1:1[b0];[s1]hue=h=8:s=0.95,eq=brightness=0.02:saturation=0.92,boxblur=1:1[b1];[s2]hue=h='-12':s=0.93,eq=brightness=0.01:saturation=0.90,boxblur=1:1[b2];[s3]hue=h=18:s=0.96,eq=brightness=0.04:saturation=0.94,boxblur=1:1[b3];[s4]hue=h='-25':s=0.91,eq=brightness=0.02:saturation=0.88,boxblur=1:1[b4];[i0][i1][i2][i3][b0][b1][b2][b3][b4]xstack=inputs=9:layout=0_0|341_0|682_0|0_192|341_192|682_192|0_384|341_384|682_384:fill=black,crop=1024:576:0:0,format=yuv420p,split=2[gridpaint][gridtop];[gridpaint][main_ref_grid]scale=w=rw:h=rh:flags=lanczos,drawbox=x=0:y=0:w=iw:h=ih:color=red:t=fill,hue=h='60*mod(floor(t*12),6)':s=2,eq=brightness='0.18*sin(2*PI*t*18)':contrast='1.30+0.20*sin(2*PI*t*18)':saturation=1.45:eval=frame[grid];[gridtop][main_ref_top]scale=w=rw:h=rh:flags=lanczos,crop=w=iw:h='floor(ih/3)':x=0:y=0,format=rgba[toprow];color=c=black:s=1024x576:r=30,format=yuv420p[maskbase];[maskbase][main_ref_mask]scale=w=rw:h=rh:flags=lanczos[maskfit];[maskfit]split=2[outlinebase][fillbase];[outlinebase]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:fontsize='min(w/3,h/3)*0.92':x=w/6-text_w/2:y=h/2-text_h/2[outlinecat1];[outlinecat1]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:fontsize='min(w/3,h/3)*0.92':x=w/2-text_w/2:y=h/2-text_h/2[outlinecat2];[outlinecat2]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:fontsize='min(w/3,h/3)*0.92':x=5*w/6-text_w/2:y=h/2-text_h/2[outlinecat3];[outlinecat3]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:fontsize='min(w/3,h/3)*0.92':x=w/6-text_w/2:y=5*h/6-text_h/2[outlinecat4];[outlinecat4]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:fontsize='min(w/3,h/3)*0.92':x=w/2-text_w/2:y=5*h/6-text_h/2[outlinecat5];[outlinecat5]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:fontsize='min(w/3,h/3)*0.92':x=5*w/6-text_w/2:y=5*h/6-text_h/2,format=gray[catoutline];[fillbase]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:borderw=24:bordercolor=white:fontsize='min(w/3,h/3)*0.70':x=w/6-text_w/2:y=h/2-text_h/2[fillcat1];[fillcat1]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:borderw=24:bordercolor=white:fontsize='min(w/3,h/3)*0.70':x=w/2-text_w/2:y=h/2-text_h/2[fillcat2];[fillcat2]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:borderw=24:bordercolor=white:fontsize='min(w/3,h/3)*0.70':x=5*w/6-text_w/2:y=h/2-text_h/2[fillcat3];[fillcat3]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:borderw=24:bordercolor=white:fontsize='min(w/3,h/3)*0.70':x=w/6-text_w/2:y=5*h/6-text_h/2[fillcat4];[fillcat4]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:borderw=24:bordercolor=white:fontsize='min(w/3,h/3)*0.70':x=w/2-text_w/2:y=5*h/6-text_h/2[fillcat5];[fillcat5]drawtext=fontfile='C\\:/Windows/Fonts/seguiemj.ttf':text='🐱':fontcolor=white:borderw=24:bordercolor=white:fontsize='min(w/3,h/3)*0.70':x=5*w/6-text_w/2:y=5*h/6-text_h/2,format=gray[fillmask];[grid]split=2[gridfill][gridlinebase];[gridfill]format=rgba[gridrgba];[gridrgba][fillmask]alphamerge[catfill];[gridlinebase]drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill,format=rgba[whitergba];[whitergba][catoutline]alphamerge[catlines];[catfill][catlines]overlay=0:0:shortest=1,format=rgba[catlayer];[catlayer][toprow]overlay=0:0:shortest=1,format=rgba[layer];[main_bg][layer]overlay=0:0:shortest=1,setsar=1[grid1];[main_blend][grid1]blend=all_expr='if(lt(N\\,3)\\,A\\,if(eq(mod(Y\\,2)\\,0)\\,A\\,B))':shortest=1,setfield=tff,format=yuv420p[vout];anoisesrc=color=pink:amplitude=0.000568:sample_rate=44100,aformat=channel_layouts=stereo[bg_noise];[0:a]aresample=44100,aformat=channel_layouts=stereo,atempo=1.0047,vibrato=f=0.266:d=0.034,volume=1.051[a_mod];[a_mod][bg_noise]amix=inputs=2:duration=first,aformat=channel_layouts=stereo,alimiter=limit=0.944,asetpts=PTS-STARTPTS[aout]"

FFARGS = {
    'metadata_format': 'ffmetadata',
    'video_map': '[vout]',
    'audio_map': '[aout]',
    'captured_video_encoder': 'libx265',
    'video_tag': 'hev1',
    'pixel_format': 'yuv420p',
    'frame_rate': '30',
    'audio_encoder': 'aac',
    'audio_bitrate': '72k',
    'audio_channels': '2',
    'audio_sample_rate': '44100',
    'container_format': 'mp4',
}

__all__ = ["FILTER_GRAPH", "FFARGS"]
