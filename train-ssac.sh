#!/bin/bash

iteration=7

tasks=(
	"StationShortestAvoidingCount" 
	# "StationShortestCount" 
)

for repeat in {1..1}
do
	for task in "${tasks[@]}"
	do
		pipenv run python -m macgraph.train \
			--dataset $task \
			\
			--tag upto_6 \
			--filter-output-class 0 \
			--filter-output-class 1 \
			--filter-output-class 2 \
			--filter-output-class 3 \
			--filter-output-class 4 \
			--filter-output-class 5 \
			--filter-output-class 6 \
			\
			--tag iter_$iteration \
			--max-decode-iterations $iteration \
			\
			--tag gs_wb_fattn_cell \
			\
			--random-seed $RANDOM \
			\
			--enable-comet \
			--train-max-steps 10 \
			--disable-control-cell \
			--disable-read-cell \
			--disable-memory-cell \
			--disable-input-bilstm \
			--enable-embed-const-eye \
			--eval-every 500 \
			--mp-state-width 1 \
			--input-width 128 \
			--embed-width 128 \
			--learning-rate 0.1 \

	done
done
