from cinemate.recommender.franchise import FranchiseInfo, collapse_franchises

COLL = {1: 7, 2: 7, 3: 7, 4: 7, 10: 8, 11: 8}  # movie -> collection
PARTS = {7: [1, 2, 3, 4], 8: [10, 11]}


def run(candidates, seen=(), liked=(), selectable=lambda _m: True):
    return collapse_franchises(
        candidates, COLL.get, lambda c: PARTS[c], set(seen), set(liked), selectable
    )


def test_unseen_franchise_shows_first_part_in_place_of_best():
    out = run([(50, 0.9), (3, 0.8), (51, 0.7), (1, 0.6), (2, 0.5)])
    assert [(m, s) for m, s, _ in out] == [(50, 0.9), (1, 0.8), (51, 0.7)]
    assert out[1][2] == FranchiseInfo(7, parts=4, unseen=4, mode="first")
    assert out[0][2] is None


def test_next_part_after_last_liked():
    out = run([(4, 0.8), (3, 0.7)], seen=[1, 2], liked=[1, 2])
    assert out == [(3, 0.8, FranchiseInfo(7, 4, 2, "next", (1, 2)))]


def test_skips_seen_parts_after_liked_one():
    out = run([(4, 0.8)], seen=[1, 2, 3], liked=[2])
    assert out[0][0] == 4 and out[0][2].mode == "next"
    assert out[0][2].rated_parts == (1, 2, 3)


def test_no_unseen_part_after_liked_falls_back_to_best_candidate():
    out = run([(1, 0.8)], seen=[2, 3, 4], liked=[4])
    assert out[0][0] == 1 and out[0][2].mode == "best"


def test_disliked_only_uses_best_candidate():
    out = run([(3, 0.8), (4, 0.5)], seen=[1], liked=[])
    assert out[0][0] == 3 and out[0][2].mode == "best"


def test_first_part_not_selectable_falls_back_to_best():
    out = run([(3, 0.8)], selectable=lambda m: m != 1)
    assert out[0][0] == 3 and out[0][2].mode == "best"


def test_no_candidates_means_collection_absent_and_plain_movies_pass():
    assert run([(50, 0.5)]) == [(50, 0.5, None)]
    assert run([]) == []
