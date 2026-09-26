package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.simulation.SimScenarioVerifySlice;
import org.springframework.data.jpa.repository.JpaRepository;

/** run 의 DES 피크 구간. 키가 run(scenario) id 그대로라 {@code findById(run.getId())} 로 읽는다. */
public interface SimScenarioVerifySliceRepository extends JpaRepository<SimScenarioVerifySlice, Long> {
}
