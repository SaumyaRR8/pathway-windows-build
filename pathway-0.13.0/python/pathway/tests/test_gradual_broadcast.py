# Copyright © 2024 Pathway

from __future__ import annotations

import pathway as pw
from pathway.tests.utils import T, assert_table_equality_wo_index

# expected markdowns are generated by the code; if the logic changes, it may need the change in the output
# the relevant part is that for a particular threshold stream, the final table should have
# the number of entries with higher value that is roughly proportional to (value-lower)/(upper-lower) fraction
# of all entries (so if value = lower, no entries should have higher value)


class TabInputSchema(pw.Schema):
    val: int
    val2: int


class ThrInputSchema(pw.Schema):
    lower: float
    value: float
    upper: float


def test_thr_stream_up():
    thr_value_functions = {
        "lower": lambda x: 10.5 + (x // 10) * 10,
        "value": lambda x: 10.5 + x,
        "upper": lambda x: 20.5 + (x // 10) * 10,
    }

    tab_value_functions = {
        "val": lambda x: 10 * (x + 1),
        "val2": lambda x: 10 * (x + 1) + 1,
    }

    thr = (
        pw.demo.generate_custom_stream(
            thr_value_functions,
            schema=ThrInputSchema,
            nb_rows=20,
            autocommit_duration_ms=5,
            input_rate=11,
        )
        .groupby()
        .reduce(
            lower=pw.reducers.max(pw.this.lower),
            value=pw.reducers.max(pw.this.value),
            upper=pw.reducers.max(pw.this.upper),
        )
    )

    tab = pw.demo.generate_custom_stream(
        tab_value_functions,
        schema=TabInputSchema,
        nb_rows=50,
        autocommit_duration_ms=10,
        input_rate=10000,
    )

    ext = tab._gradual_broadcast(
        threshold_table=thr,
        lower_column=thr.lower,
        value_column=thr.value,
        upper_column=thr.upper,
    )

    static_thr = T(
        """
      | lower   | value   | upper
    1 | 20.5    | 29.5    | 30.5
    """,
    )

    ext2 = tab._gradual_broadcast(
        static_thr,
        lower_column=static_thr.lower,
        value_column=static_thr.value,
        upper_column=static_thr.upper,
    )

    expected = T(
        """
                | val | val2 | apx_value
    ^MBW4V69... | 10  | 11   | 30.5
    ^5YWMMXY... | 20  | 21   | 30.5
    ^YJGA9S7... | 30  | 31   | 30.5
    ^TAB8G9D... | 40  | 41   | 30.5
    ^6HNVX3X... | 50  | 51   | 30.5
    ^66TAC1K... | 60  | 61   | 30.5
    ^ER9FDCM... | 70  | 71   | 30.5
    ^NT40QE3... | 80  | 81   | 30.5
    ^Y6MKAJV... | 90  | 91   | 30.5
    ^TF73PD9... | 100 | 101  | 20.5
    ^V7VAYFB... | 110 | 111  | 30.5
    ^BSVYM2Q... | 120 | 121  | 30.5
    ^5CRZCZD... | 130 | 131  | 20.5
    ^FSG9MV3... | 140 | 141  | 30.5
    ^KQHWMZ4... | 150 | 151  | 30.5
    ^WP2JX5S... | 160 | 161  | 20.5
    ^2HMVVED... | 170 | 171  | 30.5
    ^GR1PB77... | 180 | 181  | 30.5
    ^N8FE5T5... | 190 | 191  | 30.5
    ^B77YEBM... | 200 | 201  | 30.5
    ^N32QESE... | 210 | 211  | 30.5
    ^TADE6RX... | 220 | 221  | 30.5
    ^0PGNSQ6... | 230 | 231  | 30.5
    ^AF7P7GA... | 240 | 241  | 30.5
    ^A1P9G2D... | 250 | 251  | 30.5
    ^CWPSKJ5... | 260 | 261  | 30.5
    ^7RDBW71... | 270 | 271  | 30.5
    ^WN3RB6M... | 280 | 281  | 20.5
    ^HNQVTNT... | 290 | 291  | 30.5
    ^DY108CE... | 300 | 301  | 30.5
    ^BEGV4EN... | 310 | 311  | 30.5
    ^DGME9KG... | 320 | 321  | 30.5
    ^854J6ZG... | 330 | 331  | 30.5
    ^0HR0RPB... | 340 | 341  | 30.5
    ^9YJMDRV... | 350 | 351  | 30.5
    ^YBF1505... | 360 | 361  | 30.5
    ^51K17RJ... | 370 | 371  | 30.5
    ^8BKZJ3P... | 380 | 381  | 30.5
    ^FDG8S66... | 390 | 391  | 30.5
    ^J55ARGE... | 400 | 401  | 30.5
    ^P0WA6QZ... | 410 | 411  | 30.5
    ^8ND8K2T... | 420 | 421  | 30.5
    ^QHB5PGF... | 430 | 431  | 30.5
    ^3W7G401... | 440 | 441  | 30.5
    ^8KBXSGS... | 450 | 451  | 20.5
    ^P6W9470... | 460 | 461  | 30.5
    ^5Y7TW4H... | 470 | 471  | 30.5
    ^D1VQH4R... | 480 | 481  | 30.5
    ^PW7FAFG... | 490 | 491  | 30.5
    ^RC407E1... | 500 | 501  | 30.5
    """
    )

    assert_table_equality_wo_index(ext, expected)
    assert_table_equality_wo_index(ext, ext2)


def test_thr_stream_jumpy_up():
    thr_value_functions = {
        "lower": lambda x: 10.5 + ((7 * x) // 10) * 10,
        "value": lambda x: 10.5 + (7 * x),
        "upper": lambda x: 20.5 + ((7 * x) // 10) * 10,
    }

    tab_value_functions = {
        "val": lambda x: 10 * (x + 1),
        "val2": lambda x: 10 * (x + 1) + 1,
    }

    thr = (
        pw.demo.generate_custom_stream(
            thr_value_functions,
            schema=ThrInputSchema,
            nb_rows=3,
            autocommit_duration_ms=5,
            input_rate=3,
        )
        .groupby()
        .reduce(
            lower=pw.reducers.max(pw.this.lower),
            value=pw.reducers.max(pw.this.value),
            upper=pw.reducers.max(pw.this.upper),
        )
    )

    tab = pw.demo.generate_custom_stream(
        tab_value_functions,
        schema=TabInputSchema,
        nb_rows=50,
        autocommit_duration_ms=10,
        input_rate=10000,
    )

    ext = tab._gradual_broadcast(
        threshold_table=thr,
        lower_column=thr.lower,
        value_column=thr.value,
        upper_column=thr.upper,
    )

    static_thr = T(
        """
      | lower   | value   | upper
    1 | 20.5    | 24.5    | 30.5
    """,
    )

    ext2 = tab._gradual_broadcast(
        static_thr,
        lower_column=static_thr.lower,
        value_column=static_thr.value,
        upper_column=static_thr.upper,
    )

    expected = T(
        """
                | val | val2 | apx_value
    ^MBW4V69... | 10  | 11   | 20.5
    ^5YWMMXY... | 20  | 21   | 20.5
    ^YJGA9S7... | 30  | 31   | 20.5
    ^TAB8G9D... | 40  | 41   | 20.5
    ^6HNVX3X... | 50  | 51   | 20.5
    ^66TAC1K... | 60  | 61   | 20.5
    ^ER9FDCM... | 70  | 71   | 20.5
    ^NT40QE3... | 80  | 81   | 20.5
    ^Y6MKAJV... | 90  | 91   | 20.5
    ^TF73PD9... | 100 | 101  | 20.5
    ^V7VAYFB... | 110 | 111  | 20.5
    ^BSVYM2Q... | 120 | 121  | 20.5
    ^5CRZCZD... | 130 | 131  | 20.5
    ^FSG9MV3... | 140 | 141  | 20.5
    ^KQHWMZ4... | 150 | 151  | 30.5
    ^WP2JX5S... | 160 | 161  | 20.5
    ^2HMVVED... | 170 | 171  | 30.5
    ^GR1PB77... | 180 | 181  | 30.5
    ^N8FE5T5... | 190 | 191  | 30.5
    ^B77YEBM... | 200 | 201  | 20.5
    ^N32QESE... | 210 | 211  | 20.5
    ^TADE6RX... | 220 | 221  | 30.5
    ^0PGNSQ6... | 230 | 231  | 20.5
    ^AF7P7GA... | 240 | 241  | 30.5
    ^A1P9G2D... | 250 | 251  | 20.5
    ^CWPSKJ5... | 260 | 261  | 20.5
    ^7RDBW71... | 270 | 271  | 20.5
    ^WN3RB6M... | 280 | 281  | 20.5
    ^HNQVTNT... | 290 | 291  | 20.5
    ^DY108CE... | 300 | 301  | 20.5
    ^BEGV4EN... | 310 | 311  | 30.5
    ^DGME9KG... | 320 | 321  | 30.5
    ^854J6ZG... | 330 | 331  | 30.5
    ^0HR0RPB... | 340 | 341  | 30.5
    ^9YJMDRV... | 350 | 351  | 30.5
    ^YBF1505... | 360 | 361  | 30.5
    ^51K17RJ... | 370 | 371  | 20.5
    ^8BKZJ3P... | 380 | 381  | 30.5
    ^FDG8S66... | 390 | 391  | 20.5
    ^J55ARGE... | 400 | 401  | 20.5
    ^P0WA6QZ... | 410 | 411  | 20.5
    ^8ND8K2T... | 420 | 421  | 20.5
    ^QHB5PGF... | 430 | 431  | 30.5
    ^3W7G401... | 440 | 441  | 20.5
    ^8KBXSGS... | 450 | 451  | 20.5
    ^P6W9470... | 460 | 461  | 30.5
    ^5Y7TW4H... | 470 | 471  | 30.5
    ^D1VQH4R... | 480 | 481  | 30.5
    ^PW7FAFG... | 490 | 491  | 30.5
    ^RC407E1... | 500 | 501  | 30.5
    """
    )

    assert_table_equality_wo_index(ext, expected)
    assert_table_equality_wo_index(ext, ext2)


def test_thr_stream_down():
    thr_value_functions = {
        "lower": lambda x: 20.5 - (x // 10) * 10,
        "value": lambda x: 30.5 - x,
        "upper": lambda x: 30.5 - (x // 10) * 10,
    }

    tab_value_functions = {
        "val": lambda x: 10 * (x + 1),
        "val2": lambda x: 10 * (x + 1) + 1,
    }

    thr = (
        pw.demo.generate_custom_stream(
            thr_value_functions,
            schema=ThrInputSchema,
            nb_rows=20,
            autocommit_duration_ms=5,
            input_rate=11,
        )
        .groupby()
        .reduce(
            lower=pw.reducers.min(pw.this.lower),
            value=pw.reducers.min(pw.this.value),
            upper=pw.reducers.min(pw.this.upper),
        )
    )

    tab = pw.demo.generate_custom_stream(
        tab_value_functions,
        schema=TabInputSchema,
        nb_rows=50,
        autocommit_duration_ms=10,
        input_rate=10000,
    )

    ext = tab._gradual_broadcast(
        threshold_table=thr,
        lower_column=thr.lower,
        value_column=thr.value,
        upper_column=thr.upper,
    )

    static_thr = T(
        """
      | lower   | value     | upper
    1 | 10.5    | 11.5    | 20.5
    """,
    )

    ext2 = tab._gradual_broadcast(
        static_thr,
        lower_column=static_thr.lower,
        value_column=static_thr.value,
        upper_column=static_thr.upper,
    )

    expected = T(
        """
                    | val | val2 | apx_value
        ^MBW4V69... | 10  | 11   | 10.5
        ^5YWMMXY... | 20  | 21   | 10.5
        ^YJGA9S7... | 30  | 31   | 10.5
        ^TAB8G9D... | 40  | 41   | 10.5
        ^6HNVX3X... | 50  | 51   | 10.5
        ^66TAC1K... | 60  | 61   | 10.5
        ^ER9FDCM... | 70  | 71   | 10.5
        ^NT40QE3... | 80  | 81   | 10.5
        ^Y6MKAJV... | 90  | 91   | 10.5
        ^TF73PD9... | 100 | 101  | 10.5
        ^V7VAYFB... | 110 | 111  | 10.5
        ^BSVYM2Q... | 120 | 121  | 10.5
        ^5CRZCZD... | 130 | 131  | 10.5
        ^FSG9MV3... | 140 | 141  | 10.5
        ^KQHWMZ4... | 150 | 151  | 10.5
        ^WP2JX5S... | 160 | 161  | 10.5
        ^2HMVVED... | 170 | 171  | 10.5
        ^GR1PB77... | 180 | 181  | 10.5
        ^N8FE5T5... | 190 | 191  | 10.5
        ^B77YEBM... | 200 | 201  | 10.5
        ^N32QESE... | 210 | 211  | 10.5
        ^TADE6RX... | 220 | 221  | 20.5
        ^0PGNSQ6... | 230 | 231  | 10.5
        ^AF7P7GA... | 240 | 241  | 10.5
        ^A1P9G2D... | 250 | 251  | 10.5
        ^CWPSKJ5... | 260 | 261  | 10.5
        ^7RDBW71... | 270 | 271  | 10.5
        ^WN3RB6M... | 280 | 281  | 10.5
        ^HNQVTNT... | 290 | 291  | 10.5
        ^DY108CE... | 300 | 301  | 10.5
        ^BEGV4EN... | 310 | 311  | 20.5
        ^DGME9KG... | 320 | 321  | 20.5
        ^854J6ZG... | 330 | 331  | 10.5
        ^0HR0RPB... | 340 | 341  | 20.5
        ^9YJMDRV... | 350 | 351  | 10.5
        ^YBF1505... | 360 | 361  | 10.5
        ^51K17RJ... | 370 | 371  | 10.5
        ^8BKZJ3P... | 380 | 381  | 10.5
        ^FDG8S66... | 390 | 391  | 10.5
        ^J55ARGE... | 400 | 401  | 10.5
        ^P0WA6QZ... | 410 | 411  | 10.5
        ^8ND8K2T... | 420 | 421  | 10.5
        ^QHB5PGF... | 430 | 431  | 10.5
        ^3W7G401... | 440 | 441  | 10.5
        ^8KBXSGS... | 450 | 451  | 10.5
        ^P6W9470... | 460 | 461  | 10.5
        ^5Y7TW4H... | 470 | 471  | 10.5
        ^D1VQH4R... | 480 | 481  | 10.5
        ^PW7FAFG... | 490 | 491  | 10.5
        ^RC407E1... | 500 | 501  | 10.5
        """
    )

    assert_table_equality_wo_index(ext, expected)
    assert_table_equality_wo_index(ext, ext2)


def test_thr_stream_jumpy_down():
    thr_value_functions = {
        "lower": lambda x: 20.5 - ((7 * x) // 10) * 10,
        "value": lambda x: 30.5 - (7 * x),
        "upper": lambda x: 30.5 - ((7 * x) // 10) * 10,
    }

    tab_value_functions = {
        "val": lambda x: 10 * (x + 1),
        "val2": lambda x: 10 * (x + 1) + 1,
    }

    thr = (
        pw.demo.generate_custom_stream(
            thr_value_functions,
            schema=ThrInputSchema,
            nb_rows=3,
            autocommit_duration_ms=5,
            input_rate=3,
        )
        .groupby()
        .reduce(
            lower=pw.reducers.min(pw.this.lower),
            value=pw.reducers.min(pw.this.value),
            upper=pw.reducers.min(pw.this.upper),
        )
    )

    tab = pw.demo.generate_custom_stream(
        tab_value_functions,
        schema=TabInputSchema,
        nb_rows=50,
        autocommit_duration_ms=10,
        input_rate=10000,
    )

    ext = tab._gradual_broadcast(
        threshold_table=thr,
        lower_column=thr.lower,
        value_column=thr.value,
        upper_column=thr.upper,
    )

    static_thr = T(
        """
      | lower   | value     | upper
    1 | 10.5    | 16.5    | 20.5
    """,
    )

    ext2 = tab._gradual_broadcast(
        static_thr,
        lower_column=static_thr.lower,
        value_column=static_thr.value,
        upper_column=static_thr.upper,
    )

    expected = T(
        """
                | val | val2 | apx_value
    ^MBW4V69... | 10  | 11   | 10.5
    ^5YWMMXY... | 20  | 21   | 20.5
    ^YJGA9S7... | 30  | 31   | 10.5
    ^TAB8G9D... | 40  | 41   | 20.5
    ^6HNVX3X... | 50  | 51   | 10.5
    ^66TAC1K... | 60  | 61   | 10.5
    ^ER9FDCM... | 70  | 71   | 10.5
    ^NT40QE3... | 80  | 81   | 10.5
    ^Y6MKAJV... | 90  | 91   | 10.5
    ^TF73PD9... | 100 | 101  | 10.5
    ^V7VAYFB... | 110 | 111  | 10.5
    ^BSVYM2Q... | 120 | 121  | 20.5
    ^5CRZCZD... | 130 | 131  | 10.5
    ^FSG9MV3... | 140 | 141  | 10.5
    ^KQHWMZ4... | 150 | 151  | 20.5
    ^WP2JX5S... | 160 | 161  | 10.5
    ^2HMVVED... | 170 | 171  | 20.5
    ^GR1PB77... | 180 | 181  | 20.5
    ^N8FE5T5... | 190 | 191  | 20.5
    ^B77YEBM... | 200 | 201  | 10.5
    ^N32QESE... | 210 | 211  | 20.5
    ^TADE6RX... | 220 | 221  | 20.5
    ^0PGNSQ6... | 230 | 231  | 10.5
    ^AF7P7GA... | 240 | 241  | 20.5
    ^A1P9G2D... | 250 | 251  | 10.5
    ^CWPSKJ5... | 260 | 261  | 20.5
    ^7RDBW71... | 270 | 271  | 20.5
    ^WN3RB6M... | 280 | 281  | 10.5
    ^HNQVTNT... | 290 | 291  | 10.5
    ^DY108CE... | 300 | 301  | 10.5
    ^BEGV4EN... | 310 | 311  | 20.5
    ^DGME9KG... | 320 | 321  | 20.5
    ^854J6ZG... | 330 | 331  | 20.5
    ^0HR0RPB... | 340 | 341  | 20.5
    ^9YJMDRV... | 350 | 351  | 20.5
    ^YBF1505... | 360 | 361  | 20.5
    ^51K17RJ... | 370 | 371  | 10.5
    ^8BKZJ3P... | 380 | 381  | 20.5
    ^FDG8S66... | 390 | 391  | 20.5
    ^J55ARGE... | 400 | 401  | 10.5
    ^P0WA6QZ... | 410 | 411  | 10.5
    ^8ND8K2T... | 420 | 421  | 10.5
    ^QHB5PGF... | 430 | 431  | 20.5
    ^3W7G401... | 440 | 441  | 20.5
    ^8KBXSGS... | 450 | 451  | 10.5
    ^P6W9470... | 460 | 461  | 20.5
    ^5Y7TW4H... | 470 | 471  | 20.5
    ^D1VQH4R... | 480 | 481  | 20.5
    ^PW7FAFG... | 490 | 491  | 20.5
    ^RC407E1... | 500 | 501  | 20.5
    """
    )

    assert_table_equality_wo_index(ext, expected)
    assert_table_equality_wo_index(ext, ext2)


def test_thr_stream_detach():
    thr_value_functions = {
        "lower": lambda x: 10.5 + (7 * x),
        "value": lambda x: 10.5 + (7 * x) + 5,
        "upper": lambda x: 20.5 + (7 * x),
    }

    tab_value_functions = {
        "val": lambda x: 10 * (x + 1),
        "val2": lambda x: 10 * (x + 1) + 1,
    }

    thr = (
        pw.demo.generate_custom_stream(
            thr_value_functions,
            schema=ThrInputSchema,
            nb_rows=3,
            autocommit_duration_ms=5,
            input_rate=3,
        )
        .groupby()
        .reduce(
            lower=pw.reducers.max(pw.this.lower),
            value=pw.reducers.max(pw.this.value),
            upper=pw.reducers.max(pw.this.upper),
        )
    )

    tab = pw.demo.generate_custom_stream(
        tab_value_functions,
        schema=TabInputSchema,
        nb_rows=50,
        autocommit_duration_ms=10,
        input_rate=10000,
    )

    ext = tab._gradual_broadcast(
        threshold_table=thr,
        lower_column=thr.lower,
        value_column=thr.value,
        upper_column=thr.upper,
    )

    static_thr = T(
        """
      | lower   | value     | upper
    1 | 24.5    | 29.5    | 34.5
    """,
    )

    ext2 = tab._gradual_broadcast(
        static_thr,
        lower_column=static_thr.lower,
        value_column=static_thr.value,
        upper_column=static_thr.upper,
    )

    expected = T(
        """
                        | val | val2 | apx_value
            ^MBW4V69... | 10  | 11   | 24.5
            ^5YWMMXY... | 20  | 21   | 34.5
            ^YJGA9S7... | 30  | 31   | 24.5
            ^TAB8G9D... | 40  | 41   | 24.5
            ^6HNVX3X... | 50  | 51   | 24.5
            ^66TAC1K... | 60  | 61   | 24.5
            ^ER9FDCM... | 70  | 71   | 24.5
            ^NT40QE3... | 80  | 81   | 24.5
            ^Y6MKAJV... | 90  | 91   | 24.5
            ^TF73PD9... | 100 | 101  | 24.5
            ^V7VAYFB... | 110 | 111  | 24.5
            ^BSVYM2Q... | 120 | 121  | 34.5
            ^5CRZCZD... | 130 | 131  | 24.5
            ^FSG9MV3... | 140 | 141  | 24.5
            ^KQHWMZ4... | 150 | 151  | 34.5
            ^WP2JX5S... | 160 | 161  | 24.5
            ^2HMVVED... | 170 | 171  | 34.5
            ^GR1PB77... | 180 | 181  | 34.5
            ^N8FE5T5... | 190 | 191  | 34.5
            ^B77YEBM... | 200 | 201  | 24.5
            ^N32QESE... | 210 | 211  | 24.5
            ^TADE6RX... | 220 | 221  | 34.5
            ^0PGNSQ6... | 230 | 231  | 24.5
            ^AF7P7GA... | 240 | 241  | 34.5
            ^A1P9G2D... | 250 | 251  | 24.5
            ^CWPSKJ5... | 260 | 261  | 34.5
            ^7RDBW71... | 270 | 271  | 34.5
            ^WN3RB6M... | 280 | 281  | 24.5
            ^HNQVTNT... | 290 | 291  | 24.5
            ^DY108CE... | 300 | 301  | 24.5
            ^BEGV4EN... | 310 | 311  | 34.5
            ^DGME9KG... | 320 | 321  | 34.5
            ^854J6ZG... | 330 | 331  | 34.5
            ^0HR0RPB... | 340 | 341  | 34.5
            ^9YJMDRV... | 350 | 351  | 34.5
            ^YBF1505... | 360 | 361  | 34.5
            ^51K17RJ... | 370 | 371  | 24.5
            ^8BKZJ3P... | 380 | 381  | 34.5
            ^FDG8S66... | 390 | 391  | 34.5
            ^J55ARGE... | 400 | 401  | 24.5
            ^P0WA6QZ... | 410 | 411  | 24.5
            ^8ND8K2T... | 420 | 421  | 24.5
            ^QHB5PGF... | 430 | 431  | 34.5
            ^3W7G401... | 440 | 441  | 24.5
            ^8KBXSGS... | 450 | 451  | 24.5
            ^P6W9470... | 460 | 461  | 34.5
            ^5Y7TW4H... | 470 | 471  | 34.5
            ^D1VQH4R... | 480 | 481  | 34.5
            ^PW7FAFG... | 490 | 491  | 34.5
            ^RC407E1... | 500 | 501  | 34.5
        """
    )

    assert_table_equality_wo_index(ext, expected)
    assert_table_equality_wo_index(ext, ext2)
