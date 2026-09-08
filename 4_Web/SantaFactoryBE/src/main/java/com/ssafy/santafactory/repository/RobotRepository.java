package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.robot.Robot;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface RobotRepository extends JpaRepository<Robot, Long> {

    /**
     * 모델별 대표 1행 — Robots 는 로봇 개체 테이블이라 같은 모델이 대수만큼 반복된다.
     * 사양·단가는 모델이 같으면 같으므로 id 가 가장 작은 행을 카탈로그로 쓴다.
     */
    @Query("""
            select r from Robot r
            where r.id in (select min(o.id) from Robot o group by o.model)
            order by r.model
            """)
    List<Robot> findOnePerModel();
}
