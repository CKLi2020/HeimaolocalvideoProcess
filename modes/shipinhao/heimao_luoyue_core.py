import random


def shuffled_order(count, seed=None):
    order = list(range(count))
    (random.SystemRandom() if seed is None else random.Random(seed)).shuffle(order)
    return order


def filter_graph():
    return (
        "[0:v:0]fps=30,scale=720:1280:flags=lanczos,setsar=1,"
        "settb=1/60,setpts=2*N[va];"
        "[1:v:0]fps=30,scale=720:1280:force_original_aspect_ratio=increase:"
        "flags=lanczos,crop=720:1280,setsar=1,settb=1/60,setpts=2*N+1[vb];"
        "[va][vb]interleave=nb_inputs=2,settb=1/60,setpts=N[vout]"
    )


def special_offsets(durations, offsets):
    old_dts, result = 0, []
    for index, (duration, offset) in enumerate(zip(durations, offsets)):
        result.append(old_dts + offset - index * 512)
        old_dts += duration
    return result
