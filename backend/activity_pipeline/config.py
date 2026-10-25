from dataclasses import dataclass

INTERVAL_SECONDS = 15.0
SAMPLE_COUNT = 32
BATCH_SIZE = 2
PRECISION = "fp32"
PREFETCH_BATCHES = 2
BENCHMARK_SIZE = 100
SEED = 42
MIN_ACTIVITY_SCORE = 0.65
UNCERTAIN_LABEL = "Uncertain result"
ACTIVITIES = (
    "Dancing", "Rapping", "Singing", "Acting", "Speaking", "Playing sports", "Playing games",
    "Running", "Walking", "Sitting and listening", "Drawing or painting",
)
ACTIVITY_DESCRIPTIONS = {
    "Dancing": (
        "A video of one or more people dancing, with rhythmic steps, coordinated "
        "gestures, and expressive body movements in a routine or freestyle dance."
    ),
    "Rapping": (
        "A video of a person performing rap, with animated delivery, rhythmic hand "
        "gestures, and expressive movements toward an audience or camera."
    ),
    "Singing": (
        "A video of one or more people singing a song, alone or together, with "
        "visible singing expressions and performance gestures."
    ),
    "Acting": (
        "A video of people portraying characters or performing a dramatic scene, "
        "skit, or role-play, with expressive gestures, staged interactions, "
        "and theatrical movements."
    ),
    "Speaking": (
        "A video of a person speaking in conversation, giving instructions, telling "
        "a story, presenting, or addressing a group, with natural speaking gestures."
    ),
    "Playing sports": (
        "A video of people playing a sport, with athletic movements such as throwing, "
        "catching, kicking, or hitting a ball, or using sports equipment."
    ),
    "Playing games": (
        "A video of people playing a board game, card game, video game, or group game, "
        "with turn-taking, game materials, controllers, or playful group interaction."
    ),
    "Running": (
        "A video of one or more people running or jogging, with repeated running "
        "strides, active arm movements, and forward movement across an area."
    ),
    "Walking": (
        "A video of one or more people walking at a normal pace, with alternating "
        "steps and steady movement across an area."
    ),
    "Sitting and listening": (
        "A video of people sitting and facing a speaker, performer, or demonstration, "
        "mostly remaining seated while watching the activity."
    ),
    "Drawing or painting": (
        "A video of people drawing, painting, or coloring, with deliberate hand "
        "movements that make pictures or marks using pencils, markers, crayons, "
        "or paintbrushes."
    ),
}


@dataclass(frozen=True)
class FrameJob:
    frame_id: str
    video_id: int
    frame_number: int
    source_time_seconds: float
    anchor_detection_id: int
